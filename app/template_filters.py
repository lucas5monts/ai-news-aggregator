"""Jinja template filters for the web UI."""
from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse


def time_ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def card_image(url: str | None) -> str:
    """Return a card-ready image URL; prefer PNG for Contentful social cards."""
    if not url:
        return ""
    clean = unescape(url.strip())
    parsed = urlparse(clean)
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.netloc.lower() == "images.ctfassets.net":
        base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return f"{base}?w=1200&h=825&fit=fill&fm=png&q=90"
    return clean
