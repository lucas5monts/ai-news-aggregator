"""Fetch RSS/Atom feeds in parallel.

Returns a flat list of raw entries with their source attached.
Failures on individual feeds are logged but don't crash the run.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import feedparser
import httpx

log = logging.getLogger(__name__)

# How long to wait per feed before giving up
FETCH_TIMEOUT_SECONDS = 15
# Maximum bytes to read from a feed before parsing. RSS feeds should be small;
# this prevents a bad source from forcing the process to hold a huge response.
MAX_FEED_BYTES = 2_000_000
# Pretend to be a real browser so we don't get blocked by aggressive WAFs
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 (ai-news-aggregator/0.1)"
)


@dataclass
class RawEntry:
    """One feed entry with its source attached. Pre-normalization."""

    source_name: str
    source_category: str
    source_weight: float
    entry: dict[str, Any]


async def _fetch_one(
    client: httpx.AsyncClient, src: dict[str, Any]
) -> list[RawEntry]:
    """Fetch one feed; return its entries (or [] on failure)."""
    name = src["name"]
    url = src["url"]
    started = time.monotonic()
    try:
        async with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_FEED_BYTES:
                    log.warning("feed too large for %s (%s), skipping", name, url)
                    return []
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        log.warning("fetch failed for %s (%s): %s", name, url, e)
        return []

    # feedparser is sync; parse from the already-downloaded bytes
    parsed = feedparser.parse(bytes(body))
    if parsed.bozo and not parsed.entries:
        log.warning("parse failed for %s: %s", name, parsed.bozo_exception)
        return []

    elapsed_ms = (time.monotonic() - started) * 1000
    log.info(
        "fetched %s — %d entries in %.0fms", name, len(parsed.entries), elapsed_ms
    )

    return [
        RawEntry(
            source_name=name,
            source_category=src.get("category", "industry"),
            source_weight=float(src.get("weight", 1.0)),
            entry=dict(e),  # feedparser uses a custom dict-like; cast to plain dict
        )
        for e in parsed.entries
    ]


async def _fetch_all_async(sources: list[dict[str, Any]]) -> list[RawEntry]:
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        tasks = [_fetch_one(client, s) for s in sources if s.get("enabled", True)]
        results = await asyncio.gather(*tasks)
    return [entry for batch in results for entry in batch]


def fetch_all(sources: list[dict[str, Any]]) -> list[RawEntry]:
    """Sync wrapper. Pulls all enabled sources in parallel."""
    return asyncio.run(_fetch_all_async(sources))
