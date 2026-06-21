"""Render digests as plaintext or HTML email."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from jinja2 import Environment, FileSystemLoader

from .pipeline import Story

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _relative_time(dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    return f"{days}d ago"


def render_plaintext(
    stories: Iterable[Story],
    edition: str,
    category_order: list[str],
    total_scanned: int,
) -> str:
    stories = list(stories)
    now = datetime.now().strftime("%a %b %d · %I:%M %p").replace(" 0", " ")

    lines: list[str] = []
    lines.append("═" * 60)
    lines.append(f"AI NEWS DAILY · {edition.upper()} · {now}")
    lines.append("═" * 60)
    lines.append("")

    if not stories:
        lines.append("No stories matched today. Try widening the time window")
        lines.append("or relaxing the relevance keywords in config/settings.yaml.")
        lines.append("")
        lines.append("─" * 60)
        lines.append(f"Scanned {total_scanned} stories · 0 made the cut")
        return "\n".join(lines)

    by_category: dict[str, list[Story]] = {}
    for s in stories:
        by_category.setdefault(s.source_category, []).append(s)

    # keep configured order; unknown categories go at the end
    seen_cats = []
    for cat in category_order:
        if cat in by_category:
            seen_cats.append(cat)
    for cat in by_category:
        if cat not in seen_cats:
            seen_cats.append(cat)

    for cat in seen_cats:
        items = by_category[cat]
        header = f"{cat.upper()}  ({len(items)})"
        lines.append(header)
        lines.append("─" * len(header))
        for s in items:
            lines.append(f"▸ {s.title}")
            meta = f"  {s.source_name} · {_relative_time(s.published_at)}"
            lines.append(meta)
            if s.summary:
                # 2-space indent
                for chunk in _wrap(s.summary, width=72):
                    lines.append(f"  {chunk}")
            lines.append(f"  → {s.url}")
            if s.alt_sources:
                lines.append(f"  Also covered by: {' · '.join(s.alt_sources)}")
            lines.append("")
        lines.append("")

    lines.append("─" * 60)
    lines.append(
        f"Scanned {total_scanned} stories · Kept {len(stories)} · "
        f"Dropped {total_scanned - len(stories)}"
    )
    return "\n".join(lines)


def render_html(
    stories: Iterable[Story],
    edition: str,
    category_order: list[str],
    total_scanned: int,
) -> str:
    """Render the HTML email template for a digest."""
    stories = list(stories)
    now = datetime.now().strftime("%a %b %d · %I:%M %p").replace(" 0", " ")

    by_category: dict[str, list[Story]] = {}
    for s in stories:
        by_category.setdefault(s.source_category, []).append(s)

    seen_cats: list[str] = []
    for cat in category_order:
        if cat in by_category:
            seen_cats.append(cat)
    for cat in by_category:
        if cat not in seen_cats:
            seen_cats.append(cat)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    env.filters["relative_time"] = _relative_time
    template = env.get_template("digest.html.j2")

    return template.render(
        stories=stories,
        edition=edition,
        now=now,
        by_category=by_category,
        seen_cats=seen_cats,
        total_scanned=total_scanned,
    )


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap without textwrap."""
    words = text.split()
    out: list[str] = []
    line = ""
    for w in words:
        if not line:
            line = w
        elif len(line) + 1 + len(w) <= width:
            line = f"{line} {w}"
        else:
            out.append(line)
            line = w
    if line:
        out.append(line)
    return out
