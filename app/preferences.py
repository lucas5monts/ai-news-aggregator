"""Preferences blueprint — topics, schedule, sources, blocked keywords. Login required."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from flask import Blueprint, flash, render_template, request
from flask_login import current_user, login_required

from app import limiter
from .models import User, UserBlockedKeyword, UserCustomSource, UserSettings, UserSource, db
from .subscriptions import (
    DEFAULT_TZ,
    MAX_TOPIC_LEN,
    VALID_TIMEZONES,
    _TOPIC_SAFE_RE,
    _parse_form_time,
    _seed_user_defaults,
    set_user_digest_times,
    set_user_topics,
)

log = logging.getLogger(__name__)

preferences_bp = Blueprint("preferences", __name__)

MAX_BLOCKED_KEYWORDS = 50
MAX_KEYWORD_LEN = 80


def parse_blocked_keywords(raw_text: str) -> list[str]:
    """Parse comma/newline-separated blocked keywords: strip, dedupe, validate, cap."""
    import re
    if not raw_text:
        return []
    parts = re.split(r"[,\n\r]+", raw_text)
    seen: set[str] = set()
    keywords: list[str] = []
    for part in parts:
        kw = part.strip()[:MAX_KEYWORD_LEN].strip()
        if not kw:
            continue
        if not _TOPIC_SAFE_RE.match(kw):
            log.warning("parse_blocked_keywords: rejected %r", kw[:40])
            continue
        key = kw.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(kw)
        if len(keywords) >= MAX_BLOCKED_KEYWORDS:
            break
    return keywords


def set_user_blocked_keywords(user: User, raw_text: str) -> None:
    """Overwrite all blocked keywords for a user."""
    keywords = parse_blocked_keywords(raw_text)
    db.session.query(UserBlockedKeyword).filter_by(user_id=user.id).delete()
    for kw in keywords:
        db.session.add(UserBlockedKeyword(user_id=user.id, keyword=kw))


def _validate_feed_url(url: str) -> bool:
    """Fetch url and check feedparser finds at least one entry (or no parse error)."""
    try:
        import feedparser
        import httpx
        resp = httpx.get(url, timeout=5, follow_redirects=True)
        parsed = feedparser.parse(resp.content)
        return len(parsed.entries) > 0 or not parsed.bozo
    except Exception as exc:
        log.debug("_validate_feed_url(%r): %s", url, exc)
        return False


def _load_all_sources() -> list[dict]:
    p = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
    try:
        with p.open() as f:
            return yaml.safe_load(f).get("sources", [])
    except Exception as exc:
        log.warning("could not load sources.yaml: %s", exc)
        return []


def _render_editor(user: User):
    """Render the preferences form pre-filled for this user."""
    settings = db.session.get(UserSettings, user.id)
    if settings is None:
        _seed_user_defaults(user)
        db.session.commit()
        settings = db.session.get(UserSettings, user.id)

    all_sources = _load_all_sources()
    source_rows = db.session.query(UserSource).filter_by(user_id=user.id).all()
    enabled_map = {r.source_name: r.enabled for r in source_rows}
    sources = [
        {
            "name": s["name"],
            "category": s.get("category", ""),
            "enabled": enabled_map.get(s["name"], s.get("enabled", True)),
        }
        for s in all_sources
    ]
    topics = [t.topic for t in user.topics]
    custom_times = sorted(dt.send_time for dt in user.digest_times)
    blocked_keywords = [k.keyword for k in user.blocked_keywords]
    custom_sources = db.session.query(UserCustomSource).filter_by(user_id=user.id).all()

    base_url = os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/")
    referral_link = f"{base_url}/ref/{user.referral_code}" if user.referral_code else ""
    referral_count = db.session.query(User).filter_by(referred_by_id=user.id).count()

    return render_template(
        "preferences.html",
        email=user.email,
        topics_text=", ".join(topics),
        settings=settings,
        sources=sources,
        custom_times=custom_times,
        initial_times=custom_times,
        blocked_keywords_text=", ".join(blocked_keywords),
        custom_sources=custom_sources,
        referral_link=referral_link,
        referral_count=referral_count,
    )


@preferences_bp.route("/preferences", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour")
@login_required
def preferences():
    user = current_user

    if request.method == "GET":
        return _render_editor(user)

    try:
        settings = db.session.get(UserSettings, user.id)
        if settings is None:
            _seed_user_defaults(user)
            db.session.flush()
            settings = db.session.get(UserSettings, user.id)

        settings.morning_enabled = "morning_enabled" in request.form
        settings.evening_enabled = "evening_enabled" in request.form
        settings.send_email = "send_email" in request.form
        settings.morning_time = _parse_form_time(
            request.form.get("morning_time", ""), settings.morning_time or "06:00"
        )
        settings.evening_time = _parse_form_time(
            request.form.get("evening_time", ""), settings.evening_time or "20:00"
        )

        tz = request.form.get("timezone", DEFAULT_TZ).strip()
        if tz not in VALID_TIMEZONES:
            tz = DEFAULT_TZ
        settings.timezone = tz

        all_sources = _load_all_sources()
        selected = set(request.form.getlist("sources"))
        for src in all_sources:
            name = src["name"]
            row = db.session.get(UserSource, (user.id, name))
            if row is None:
                row = UserSource(user_id=user.id, source_name=name, enabled=True)
                db.session.add(row)
            row.enabled = name in selected

        set_user_topics(user, request.form.get("topics", ""))
        set_user_digest_times(user, request.form.getlist("custom_times"))
        set_user_blocked_keywords(user, request.form.get("blocked_keywords", ""))

        # Custom RSS sources
        urls = request.form.getlist("custom_source_url")
        names = request.form.getlist("custom_source_name")
        db.session.query(UserCustomSource).filter_by(user_id=user.id).delete()
        for url, name in zip(urls, names):
            url = url.strip()
            name = name.strip()
            if not url or not name:
                continue
            if not _validate_feed_url(url):
                flash(f"Feed URL could not be validated and was skipped: {url}", "error")
                continue
            db.session.add(UserCustomSource(
                user_id=user.id,
                url=url,
                name=name,
                enabled=True,
            ))

        db.session.commit()
        flash("Your preferences have been saved.", "success")
        log.info("preferences updated for user_id=%s", user.id)
        return _render_editor(user)
    except Exception as exc:
        log.error("preferences save failed for user_id=%s: %s", user.id, exc)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return _render_editor(user), 500
