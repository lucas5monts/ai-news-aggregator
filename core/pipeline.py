"""Normalize raw RSS entries, filter for relevance, rank, and dedupe.

Pipeline: normalize → relevance filter → recency rank → fuzzy dedupe.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

from rapidfuzz import fuzz

from .fetch import RawEntry

log = logging.getLogger(__name__)


@dataclass
class Story:
    """A normalized, scored story ready to render."""

    id: str  # stable hash of canonical URL
    title: str
    url: str
    summary: str
    source_name: str
    source_category: str
    published_at: datetime
    score: float = 0.0
    image_url: str | None = None
    matched_topic: str | None = None  # user interest that best matched this story
    llm_score: float | None = None  # raw LLM relevance score (0.0–1.0)
    # Phase 2: alt_sources collects other sources covering the same story
    alt_sources: list[str] = field(default_factory=list)


# --- helpers -----------------------------------------------------------------


class _StripTags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)


def _strip_html(text: str) -> str:
    if not text:
        return ""
    p = _StripTags()
    p.feed(text)
    return re.sub(r"\s+", " ", "".join(p.chunks)).strip()


def _parse_date(entry: dict[str, Any]) -> datetime:
    """Best-effort published-time extraction. Falls back to now if missing."""
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if not val:
            continue
        try:
            dt = parsedate_to_datetime(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue

    # feedparser also exposes a parsed struct_time — try that as a fallback
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue

    log.debug("no parsable date on entry; falling back to now")
    return datetime.now(timezone.utc)


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


_IMG_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|gif|avif)(?:[?#]|$)", re.I)
_IMG_TAG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)["']""", re.I)


def _looks_like_image(url: str) -> bool:
    return bool(url) and bool(_IMG_EXT_RE.search(url))


def _extract_image(entry: dict[str, Any]) -> str | None:
    """Best-effort thumbnail from RSS media tags or embedded HTML.

    Checks every common place feeds stash a hero image, in rough order of
    reliability, so as many stories as possible get a real picture before we
    fall back to a live og:image fetch.
    """
    # 1. Media RSS thumbnail
    for thumb in entry.get("media_thumbnail") or []:
        url = thumb.get("url")
        if url:
            return url

    # 2. Media RSS content (image medium/type, or an image-looking URL)
    for media in entry.get("media_content") or []:
        url = media.get("url")
        medium = media.get("medium", "")
        mtype = media.get("type", "")
        if url and (medium == "image" or str(mtype).startswith("image/") or _looks_like_image(url)):
            return url

    # 3. Enclosures (podcast/news feeds often attach the hero here)
    for enc in entry.get("enclosures") or []:
        href = enc.get("href") or enc.get("url")
        if href and (str(enc.get("type", "")).startswith("image/") or _looks_like_image(href)):
            return href

    # 4. Atom <link rel="enclosure"> image links
    for link in entry.get("links") or []:
        href = link.get("href")
        if href and link.get("rel") == "enclosure" and (
            str(link.get("type", "")).startswith("image/") or _looks_like_image(href)
        ):
            return href

    # 5. feedparser's parsed entry.image
    image = entry.get("image")
    if isinstance(image, dict):
        href = image.get("href") or image.get("url")
        if href:
            return href

    # 6. First <img> in summary / description / full content HTML
    html_blobs = [entry.get("summary") or "", entry.get("description") or ""]
    for content in entry.get("content") or []:
        if isinstance(content, dict) and content.get("value"):
            html_blobs.append(content["value"])
    for html in html_blobs:
        match = _IMG_TAG_RE.search(html)
        if match:
            return match.group(1)

    return None


# --- main pipeline -----------------------------------------------------------


def normalize(raw: list[RawEntry], max_summary_chars: int = 280) -> list[Story]:
    out: list[Story] = []
    for r in raw:
        e = r.entry
        url = e.get("link") or e.get("id") or ""
        title = _strip_html(e.get("title") or "").strip()
        if not url or not title:
            continue
        summary = _strip_html(e.get("summary") or e.get("description") or "")
        out.append(
            Story(
                id=_stable_id(url),
                title=title,
                url=url,
                summary=_truncate(summary, max_summary_chars),
                source_name=r.source_name,
                source_category=r.source_category,
                published_at=_parse_date(e),
                image_url=_extract_image(e),
            )
        )
    return out


def filter_relevant(
    stories: list[Story], keywords: list[str], window_hours: int
) -> list[Story]:
    """Drop stories older than the window or that don't match any keyword.

    Empty keyword list = pass everything through (used for already-curated feeds).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    lowered = [k.lower() for k in keywords]
    kept: list[Story] = []
    dropped_age = dropped_kw = 0

    for s in stories:
        if s.published_at < cutoff:
            dropped_age += 1
            continue
        if lowered:
            haystack = f"{s.title}\n{s.summary}".lower()
            if not any(k in haystack for k in lowered):
                dropped_kw += 1
                continue
        kept.append(s)

    log.info(
        "filter: kept %d, dropped %d (old) + %d (off-topic)",
        len(kept),
        dropped_age,
        dropped_kw,
    )
    return kept


def rank(stories: list[Story], source_weights: dict[str, float]) -> list[Story]:
    """Score = recency_score * source_weight.

    Recency: 1.0 for "just now" decaying to ~0.1 at the 24h mark.
    """
    now = datetime.now(timezone.utc)
    for s in stories:
        age_hours = max(0.0, (now - s.published_at).total_seconds() / 3600)
        recency = max(0.1, 1.0 - (age_hours / 24.0) * 0.9)
        weight = source_weights.get(s.source_name, 1.0)
        s.score = recency * weight
    stories.sort(key=lambda s: s.score, reverse=True)
    return stories


def cap(stories: list[Story], n: int) -> list[Story]:
    return stories[:n]


# Titles matching these patterns are promotional junk (coupons, deals, etc.)
# and should never appear on a news feed.
_JUNK_RE = re.compile(
    r"\b("
    r"coupon|promo\s*code|discount\s*code|voucher|"
    r"\d+%\s*off|save\s+\$?\d+|deal\s+of\s+the|"
    r"best\s+deals?|shop\s+now|buy\s+now|limited\s+offer|"
    r"free\s+shipping|cashback|rebate|sale\s+ends"
    r")\b",
    re.I,
)


def filter_junk(stories: list[Story]) -> list[Story]:
    """Drop promotional / coupon stories based on title patterns."""
    kept = [s for s in stories if not _JUNK_RE.search(s.title)]
    dropped = len(stories) - len(kept)
    if dropped:
        log.info("filter_junk: dropped %d promotional stories", dropped)
    return kept


_STOPWORDS = frozenset({"the", "a", "is", "for", "to"})
_DEDUPE_THRESHOLD = 90


def _normalize_title(title: str) -> str:
    lowered = title.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    tokens = [t for t in cleaned.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def dedupe(stories: list[Story]) -> list[Story]:
    """Collapse near-duplicate titles across sources; keep highest-scored primary."""
    if not stories:
        log.info("dedupe: 0 stories collapsed into 0 clusters (0 primaries kept)")
        return []

    n = len(stories)
    norms = [_normalize_title(s.title) for s in stories]
    uf = _UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            if fuzz.token_set_ratio(norms[i], norms[j]) >= _DEDUPE_THRESHOLD:
                uf.union(i, j)

    clusters: dict[int, list[Story]] = {}
    for i, story in enumerate(stories):
        clusters.setdefault(uf.find(i), []).append(story)

    result: list[Story] = []
    collapsed = 0
    multi_clusters = 0

    for members in clusters.values():
        members.sort(key=lambda s: s.score, reverse=True)
        primary = members[0]
        alt: list[str] = []
        seen = {primary.source_name}
        for m in members[1:]:
            if m.source_name not in seen:
                alt.append(m.source_name)
                seen.add(m.source_name)
        primary.alt_sources = alt
        result.append(primary)
        if len(members) > 1:
            multi_clusters += 1
            collapsed += len(members) - 1

    result.sort(key=lambda s: s.score, reverse=True)
    log.info(
        "dedupe: %d stories collapsed into %d clusters (%d primaries kept)",
        collapsed,
        multi_clusters,
        len(result),
    )
    return result
