"""RSS entry pipeline: normalize → filter → rank → dedupe."""
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
    """Normalized story, post-pipeline."""

    id: str  # stable hash of canonical URL
    title: str
    url: str
    summary: str
    source_name: str
    source_category: str
    published_at: datetime
    score: float = 0.0
    image_url: str | None = None
    matched_topic: str | None = None  # which user topic triggered this story
    llm_score: float | None = None  # 0.0–1.0 from LLM scorer
    # other sources covering the same story (populated by dedupe)
    alt_sources: list[str] = field(default_factory=list)
    # full-coverage clustering (populated by cluster_stories)
    cluster_stories: list = field(default_factory=list)
    cluster_count: int = 1


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
    """Parse published date from feed entry; falls back to now."""
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

    # also try feedparser's struct_time
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue

    log.debug("no parsable date; falling back to now")
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
    """Extract best available thumbnail from RSS media tags or embedded HTML."""
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
    """Drop stories outside the time window or missing any keyword. Empty keywords = keep all."""
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
    """score = recency × source_weight. Recency decays from 1.0 to ~0.1 over 24h."""
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


# junk title patterns — coupons/deals that slip through curated feeds
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
    """Drop coupon/promo stories by title regex."""
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
    """Fuzzy-dedupe by title; keeps highest-scored story per cluster, collects alt_sources."""
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


_CLUSTER_THRESHOLD = 72  # tuned for news titles


def cluster_stories(stories: list[Story]) -> list[Story]:
    """Group stories about the same event into clusters for 'Full Coverage' display.

    The highest-scoring story becomes the primary; others attach as .cluster_stories.
    Unlike dedupe (which collapses to one), this preserves all stories but annotates
    the primary with related coverage so the UI can surface them.
    """
    from rapidfuzz.fuzz import token_sort_ratio

    used: set[int] = set()
    result: list[Story] = []

    for i, primary in enumerate(stories):
        if i in used:
            continue
        cluster: list[Story] = []
        for j, candidate in enumerate(stories):
            if j == i or j in used:
                continue
            score = token_sort_ratio(primary.title, candidate.title)
            if score >= _CLUSTER_THRESHOLD:
                cluster.append(candidate)
                used.add(j)
        used.add(i)
        primary.cluster_stories = cluster
        primary.cluster_count = len(cluster) + 1
        result.append(primary)

    clustered = sum(1 for s in result if s.cluster_count > 1)
    log.info("cluster_stories: %d stories → %d primary cards (%d with multiple sources)", len(stories), len(result), clustered)
    return result
