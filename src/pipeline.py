"""Normalize raw RSS entries, filter for relevance, and rank.

Phase 1 keeps this small: normalize → relevance filter → simple recency rank.
Phase 2 will add rapidfuzz-based dedupe across sources.
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
