"""Bookmark blueprint — toggle and list saved stories."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from flask import Blueprint, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import text

from app import limiter
from app.models import UserBookmark, db

log = logging.getLogger(__name__)

bookmarks_bp = Blueprint("bookmarks", __name__)


def _fetch_story(story_id: str) -> SimpleNamespace | None:
    """Look up one story from the raw SQLite stories table. Returns None if not found."""
    try:
        with db.engine.connect() as conn:
            result = conn.execute(
                text("SELECT id, title, url, summary, source_name, published_at FROM stories WHERE id = :sid"),
                {"sid": story_id},
            )
            row = result.fetchone()
            if row is None:
                return None
            pub = row[5]
            if isinstance(pub, str):
                try:
                    pub = datetime.fromisoformat(pub)
                    if pub.tzinfo is None:
                        pub = pub.replace(tzinfo=timezone.utc)
                except Exception:
                    pub = datetime.now(timezone.utc)
            return SimpleNamespace(
                id=row[0],
                title=row[1],
                url=row[2],
                summary=row[3],
                source_name=row[4],
                source_category="",
                published_at=pub,
                image_url=None,
                matched_topic=None,
                llm_score=None,
                alt_sources=[],
            )
    except Exception as exc:
        log.error("_fetch_story error: %s", exc)
        return None


@bookmarks_bp.route("/bookmark/<story_id>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def toggle_bookmark(story_id: str):
    """Toggle a bookmark; returns the HTMX button snippet for swap."""
    existing = db.session.get(UserBookmark, (current_user.id, story_id))
    if existing:
        db.session.delete(existing)
        db.session.commit()
        bookmarked = False
    else:
        bm = UserBookmark(
            user_id=current_user.id,
            story_id=story_id,
            bookmarked_at=datetime.now(timezone.utc),
        )
        db.session.add(bm)
        db.session.commit()
        bookmarked = True

    return render_template("_bookmark_btn.html", story_id=story_id, bookmarked=bookmarked)


@bookmarks_bp.route("/bookmarks")
@login_required
def bookmarks():
    """Bookmarks page — fetch saved stories in reverse chronological order."""
    rows = (
        db.session.query(UserBookmark)
        .filter_by(user_id=current_user.id)
        .order_by(UserBookmark.bookmarked_at.desc())
        .all()
    )
    stories = []
    bookmarked_ids = set()
    for row in rows:
        story = _fetch_story(row.story_id)
        if story:
            stories.append(story)
            bookmarked_ids.add(row.story_id)

    return render_template(
        "bookmarks.html",
        stories=stories,
        bookmarked_ids=bookmarked_ids,
    )
