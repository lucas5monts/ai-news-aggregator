"""Main application routes for the AI News Dashboard.

All routes require authentication (via @login_required) except the root
redirect. The dev-user escape hatch (FLASK_ENV=development, auto-login the
first/only user) is handled in create_app(), not here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from .models import Digest, DigestStory, UserSettings, UserSource, db

log = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _load_sources_yaml() -> list[dict]:
    p = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
    with p.open() as f:
        return yaml.safe_load(f).get("sources", [])


def _load_settings_yaml() -> dict:
    p = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
    with p.open() as f:
        return yaml.safe_load(f)


def _get_user_sources(user_id: int) -> dict[str, bool]:
    """Return {source_name: enabled} for the given user."""
    rows = db.session.query(UserSource).filter_by(user_id=user_id).all()
    return {r.source_name: r.enabled for r in rows}


def _run_pipeline_for_user(user_id: int) -> tuple[list, int]:
    """Fetch + pipeline for the current user's enabled sources.

    Returns (stories, total_scanned).
    """
    from core import fetch, pipeline

    all_sources = _load_sources_yaml()
    settings_yaml = _load_settings_yaml()

    user_source_map = _get_user_sources(user_id)
    # Filter master source list to those the user has enabled
    user_sources = [
        s for s in all_sources
        if user_source_map.get(s["name"], s.get("enabled", True))
    ]

    keywords = settings_yaml.get("relevance_keywords") or []
    max_summary_chars = int(settings_yaml.get("digest", {}).get("max_summary_chars", 280))

    user_settings = db.session.get(UserSettings, user_id)
    max_stories = user_settings.max_stories if user_settings else 15
    window_hours = 24  # morning window

    raw = fetch.fetch_all(user_sources)
    total_scanned = len(raw)

    stories = pipeline.normalize(raw, max_summary_chars=max_summary_chars)
    stories = pipeline.filter_relevant(stories, keywords, window_hours)

    source_weights = {s["name"]: float(s.get("weight", 1.0)) for s in all_sources}
    stories = pipeline.rank(stories, source_weights)
    stories = pipeline.dedupe(stories)
    stories = pipeline.cap(stories, max_stories)

    return stories, total_scanned


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@main_bp.route("/")
def index():
    return redirect(url_for("main.feed"))


@main_bp.route("/feed")
@login_required
def feed():
    log.info("GET /feed user_id=%s", current_user.id)
    try:
        stories, total_scanned = _run_pipeline_for_user(current_user.id)
    except Exception as exc:
        log.error("feed pipeline error: %s", exc)
        stories, total_scanned = [], 0
        flash("Could not fetch stories. Check your internet connection.", "error")
    return render_template(
        "feed.html",
        stories=stories,
        total_scanned=total_scanned,
    )


@main_bp.route("/feed/refresh", methods=["POST"])
@login_required
def feed_refresh():
    log.info("POST /feed/refresh user_id=%s", current_user.id)
    try:
        stories, total_scanned = _run_pipeline_for_user(current_user.id)
    except Exception as exc:
        log.error("feed refresh error: %s", exc)
        stories, total_scanned = [], 0
    return render_template(
        "feed_items.html",
        stories=stories,
        total_scanned=total_scanned,
    )


@main_bp.route("/settings", methods=["GET"])
@login_required
def settings():
    log.info("GET /settings user_id=%s", current_user.id)
    all_sources = _load_sources_yaml()
    user_source_map = _get_user_sources(current_user.id)
    user_settings = db.session.get(UserSettings, current_user.id)
    if user_settings is None:
        user_settings = UserSettings(user_id=current_user.id)
        db.session.add(user_settings)
        db.session.commit()
    return render_template(
        "settings.html",
        all_sources=all_sources,
        user_source_map=user_source_map,
        user_settings=user_settings,
    )


@main_bp.route("/settings", methods=["POST"])
@login_required
def settings_post():
    log.info("POST /settings user_id=%s", current_user.id)
    user_settings = db.session.get(UserSettings, current_user.id)
    if user_settings is None:
        user_settings = UserSettings(user_id=current_user.id)
        db.session.add(user_settings)

    # Global toggles
    user_settings.send_email = "send_email" in request.form
    user_settings.morning_enabled = "morning_enabled" in request.form
    user_settings.evening_enabled = "evening_enabled" in request.form
    user_settings.timezone = request.form.get("timezone", "America/Los_Angeles")
    try:
        user_settings.max_stories = max(1, min(50, int(request.form.get("max_stories", 15))))
    except (TypeError, ValueError):
        user_settings.max_stories = 15

    # Per-source toggles — form sends source_<name> checkboxes
    all_sources = _load_sources_yaml()
    for src in all_sources:
        name = src["name"]
        enabled = f"source_{name}" in request.form
        us = db.session.get(UserSource, (current_user.id, name))
        if us is None:
            us = UserSource(user_id=current_user.id, source_name=name, enabled=enabled)
            db.session.add(us)
        else:
            us.enabled = enabled

    db.session.commit()

    # HTMX partial response
    user_source_map = _get_user_sources(current_user.id)
    return render_template(
        "settings_form.html",
        all_sources=all_sources,
        user_source_map=user_source_map,
        user_settings=user_settings,
        saved=True,
    )


@main_bp.route("/preview")
@login_required
def preview():
    log.info("GET /preview user_id=%s", current_user.id)
    settings_yaml = _load_settings_yaml()
    category_order = settings_yaml.get("digest", {}).get(
        "category_order", ["industry", "research", "tools", "policy"]
    )
    try:
        stories, total_scanned = _run_pipeline_for_user(current_user.id)
        from core.render import render_html
        html_content = render_html(
            stories,
            edition="test",
            category_order=category_order,
            total_scanned=total_scanned,
        )
    except Exception as exc:
        log.error("preview render error: %s", exc)
        html_content = "<p>Error rendering preview.</p>"
        stories = []
        total_scanned = 0

    return render_template(
        "preview.html",
        html_content=html_content,
        story_count=len(stories),
    )


@main_bp.route("/preview/send", methods=["POST"])
@login_required
def preview_send():
    log.info("POST /preview/send user_id=%s", current_user.id)
    settings_yaml = _load_settings_yaml()
    category_order = settings_yaml.get("digest", {}).get(
        "category_order", ["industry", "research", "tools", "policy"]
    )
    try:
        stories, total_scanned = _run_pipeline_for_user(current_user.id)
        from core.render import render_html, render_plaintext
        from core.deliver import build_subject, load_email_config, send_digest

        html = render_html(stories, edition="test", category_order=category_order,
                           total_scanned=total_scanned)
        plaintext = render_plaintext(stories, edition="test", category_order=category_order,
                                     total_scanned=total_scanned)
        subject = build_subject("test", len(stories))

        cfg = load_email_config()
        send_digest(
            subject=subject,
            plaintext=plaintext,
            html=html,
            to_address=current_user.email,
            from_address=cfg["GMAIL_ADDRESS"],
            app_password=cfg["GMAIL_APP_PASSWORD"],
        )

        # Log the digest
        digest = Digest(
            user_id=current_user.id,
            edition="test",
            sent_at=datetime.now(timezone.utc),
            story_count=len(stories),
            subject=subject,
            html_blob=html,
        )
        db.session.add(digest)
        db.session.flush()
        for s in stories:
            db.session.add(DigestStory(digest_id=digest.id, story_id=s.id))
        db.session.commit()

        flash(f"Test digest sent to {current_user.email} ({len(stories)} stories).", "success")
    except Exception as exc:
        log.error("preview send error: %s", exc)
        flash(f"Failed to send: {exc}", "error")

    return redirect(url_for("main.preview"))


@main_bp.route("/archive")
@login_required
def archive():
    log.info("GET /archive user_id=%s", current_user.id)
    digests = (
        db.session.query(Digest)
        .filter_by(user_id=current_user.id)
        .order_by(Digest.sent_at.desc())
        .all()
    )
    return render_template("archive.html", digests=digests)


@main_bp.route("/archive/<int:digest_id>")
@login_required
def archive_view(digest_id: int):
    log.info("GET /archive/%d user_id=%s", digest_id, current_user.id)
    digest = db.session.get(Digest, digest_id)
    if digest is None or digest.user_id != current_user.id:
        flash("Digest not found.", "error")
        return redirect(url_for("main.archive"))
    return render_template("archive_view.html", digest=digest)
