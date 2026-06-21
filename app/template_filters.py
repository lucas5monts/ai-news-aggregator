"""Custom Jinja filters."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse
from xml.sax.saxutils import escape as _xml_escape


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


def safe_url(url: str) -> str:
    """Block non-http(s) schemes; returns '#' for data:, javascript:, etc."""
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https"):
            return url
    except Exception:
        pass
    return "#"


def card_image(url: str | None) -> str:
    """Normalize an image URL; rewrites Contentful URLs to force PNG."""
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


# Category → (gradient start, gradient end) for placeholder tiles.
_PLACEHOLDER_COLORS = {
    "world": ("#4f46e5", "#7c3aed"),
    "us": ("#0ea5e9", "#2563eb"),
    "tech": ("#6366f1", "#a855f7"),
    "ai": ("#059669", "#0891b2"),
    "business": ("#d97706", "#dc2626"),
    "science": ("#0891b2", "#2563eb"),
    "politics": ("#e11d48", "#db2777"),
    "sports": ("#16a34a", "#65a30d"),
}


def reading_time(text: str) -> int:
    """Reading time in minutes at ~200 wpm."""
    return max(1, len((text or "").split()) // 200)


def placeholder_image(source_name: str | None = "", category: str | None = "") -> str:
    """SVG placeholder branded with source name and category color, as a data URI."""
    c1, c2 = _PLACEHOLDER_COLORS.get((category or "").lower(), ("#4f46e5", "#9333ea"))
    label = _xml_escape((source_name or "News").strip()[:42])
    cat = _xml_escape((category or "").upper())
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="500" viewBox="0 0 800 500">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        '</linearGradient></defs>'
        '<rect width="800" height="500" fill="url(#g)"/>'
        '<circle cx="230" cy="110" r="280" fill="rgba(255,255,255,0.10)"/>'
        '<circle cx="640" cy="430" r="200" fill="rgba(0,0,0,0.10)"/>'
        f'<text x="50%" y="47%" text-anchor="middle" font-family="Georgia,\'Times New Roman\',serif" '
        f'font-size="48" font-weight="700" fill="rgba(255,255,255,0.96)">{label}</text>'
        f'<text x="50%" y="57%" text-anchor="middle" font-family="Arial,sans-serif" '
        f'font-size="20" letter-spacing="4" fill="rgba(255,255,255,0.72)">{cat}</text>'
        '</svg>'
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"
