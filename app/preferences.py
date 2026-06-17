"""Subscriber preferences — edit topics, schedule, and sources (login required)."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from flask import Blueprint, flash, render_template, request
from flask_login import current_user, login_required

from app import limiter
from .models import User, UserSettings, UserSource, db
from .subscriptions import (
    DEFAULT_TZ,
    VALID_TIMEZONES,
    _parse_form_time,
    _seed_user_defaults,
    set_user_digest_times,
    set_user_topics,
)

log = logging.getLogger(__name__)

preferences_bp = Blueprint("preferences", __name__)


def _load_all_sources() -> list[dict]:
    p = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
    try:
        with p.open() as f:
            return yaml.safe_load(f).get("sources", [])
    except Exception as exc:
        log.warning("could not load sources.yaml: %s", exc)
        return []


def _render_editor(user: User):
    """Render the preferences editor pre-filled for *user*."""
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

    return render_template(
        "preferences.html",
        email=user.email,
        topics_text=", ".join(topics),
        settings=settings,
        sources=sources,
        custom_times=custom_times,
        initial_times=custom_times,
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
        db.session.commit()
        flash("Your preferences have been saved.", "success")
        log.info("preferences updated for user_id=%s", user.id)
        return _render_editor(user)
    except Exception as exc:
        log.error("preferences save failed for user_id=%s: %s", user.id, exc)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return _render_editor(user), 500
