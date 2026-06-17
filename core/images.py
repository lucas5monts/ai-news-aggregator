"""Fetch article hero images from page metadata (Open Graph / Twitter cards).

Used when RSS feeds don't include a thumbnail. Results are cached in memory
so repeat feed loads stay fast.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx

from .fetch import USER_AGENT
from .pipeline import Story

log = logging.getLogger(__name__)

READ_LIMIT_BYTES = 384_000
FETCH_TIMEOUT_SECONDS = 8
MAX_CONCURRENT = 6
CACHE_TTL_HIT = 86_400   # 24h for successful lookups
CACHE_TTL_MISS = 3_600   # 1h for failures (article may update)

# property/name → content, or content → property/name
_META_IMAGE = re.compile(
    r"""<meta[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["']"""
    r"""[^>]+content=["']([^"']+)["']""",
    re.I,
)
_META_IMAGE_REV = re.compile(
    r"""<meta[^>]+content=["']([^"']+)["']"""
    r"""[^>]+(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["']""",
    re.I,
)
_LINK_IMAGE = re.compile(
    r"""<link[^>]+rel=["']image_src["'][^>]+href=["']([^"']+)["']""",
    re.I,
)
_ITEMPROP_IMAGE = re.compile(
    r"""<meta[^>]+itemprop=["']image["'][^>]+content=["']([^"']+)["']""",
    re.I,
)
# JSON-LD "image": "https://..."  or  "image": ["https://...", ...]
_JSONLD_IMAGE = re.compile(
    r""""image"\s*:\s*(?:\[\s*)?["'](https?://[^"']+)["']""",
    re.I,
)

_cache: dict[str, tuple[float, str | None]] = {}


def _cache_get(url: str) -> str | None | _CacheMiss:
    row = _cache.get(url)
    if row is None:
        return _CacheMiss()
    expires, image = row
    if time.monotonic() > expires:
        del _cache[url]
        return _CacheMiss()
    return image


class _CacheMiss:
    pass


def _cache_set(url: str, image: str | None) -> None:
    ttl = CACHE_TTL_HIT if image else CACHE_TTL_MISS
    _cache[url] = (time.monotonic() + ttl, image)


def _normalize_image_url(raw: str, page_url: str) -> str | None:
    # og:image content often uses HTML entities (&amp;) — decode before use.
    raw = html.unescape(raw.strip())
    if not raw or raw.startswith("data:"):
        return None
    absolute = urljoin(page_url, raw)
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    lower = absolute.lower()
    if any(bad in lower for bad in ("/favicon", "pixel.", "1x1", "spacer.gif")):
        return None
    return absolute


def parse_og_image(html: str, page_url: str) -> str | None:
    """Extract the best social preview image from partial page HTML."""
    for pattern in (_META_IMAGE, _META_IMAGE_REV, _LINK_IMAGE, _ITEMPROP_IMAGE, _JSONLD_IMAGE):
        match = pattern.search(html)
        if match:
            url = _normalize_image_url(match.group(1), page_url)
            if url:
                return url
    return None


def _is_safe_url(url: str) -> bool:
    """Return False if the URL resolves to a private/loopback/link-local IP."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return ip.is_global and not ip.is_private and not ip.is_loopback and not ip.is_link_local and not ip.is_reserved
    except Exception:
        return False


async def _fetch_og_one(client: httpx.AsyncClient, article_url: str) -> str | None:
    if not _is_safe_url(article_url):
        return None

    cached = _cache_get(article_url)
    if not isinstance(cached, _CacheMiss):
        return cached

    try:
        async with client.stream("GET", article_url, follow_redirects=True) as resp:
            resp.raise_for_status()
            final_url = str(resp.url)
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) >= READ_LIMIT_BYTES:
                    break
        html = bytes(buf).decode("utf-8", errors="ignore")
        image = parse_og_image(html, final_url)
        _cache_set(article_url, image)
        if image:
            log.debug("og:image found for %s", article_url)
        return image
    except Exception as exc:
        log.debug("og:image fetch failed for %s: %s", article_url, exc)
        _cache_set(article_url, None)
        return None


async def _enrich_async(stories: list[Story]) -> None:
    missing = [s for s in stories if not s.image_url]
    if not missing:
        return

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:

        async def _one(story: Story) -> None:
            async with sem:
                story.image_url = await _fetch_og_one(client, story.url)

        await asyncio.gather(*[_one(s) for s in missing])

    found = sum(1 for s in missing if s.image_url)
    log.info("og:image enrichment: %d/%d stories got images", found, len(missing))


def enrich_story_images(stories: list[Story]) -> list[Story]:
    """Fill missing ``image_url`` values from article Open Graph metadata."""
    if not stories:
        return stories
    try:
        asyncio.run(_enrich_async(stories))
    except RuntimeError:
        # Already inside an event loop (unlikely in Flask sync context)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_enrich_async(stories))
        finally:
            loop.close()
    return stories


def clear_image_cache() -> None:
    """Clear the in-memory cache (useful in tests)."""
    _cache.clear()
