"""Main application routes for the AI News Dashboard.

All routes are public — no login required. Subscribers sign up via /subscribe.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from flask import Blueprint, flash, redirect, render_template, url_for

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


def _run_pipeline_global() -> tuple[list, int]:
    """Fetch + pipeline using global config defaults."""
    from core import fetch, pipeline

    all_sources = _load_sources_yaml()
    settings_yaml = _load_settings_yaml()

    user_sources = [s for s in all_sources if s.get("enabled", True)]

    keywords = settings_yaml.get("relevance_keywords") or []
    max_summary_chars = int(settings_yaml.get("digest", {}).get("max_summary_chars", 280))
    max_stories = int(settings_yaml.get("max_stories", 15))
    window_hours = int(settings_yaml.get("default_time_window_hours", 24))

    raw = fetch.fetch_all(user_sources)
    total_scanned = len(raw)

    stories = pipeline.normalize(raw, max_summary_chars=max_summary_chars)
    stories = pipeline.filter_relevant(stories, keywords, window_hours)

    source_weights = {s["name"]: float(s.get("weight", 1.0)) for s in all_sources}
    stories = pipeline.rank(stories, source_weights)
    stories = pipeline.dedupe(stories)
    stories = pipeline.cap(stories, max_stories)

    from core.images import enrich_story_images
    stories = enrich_story_images(stories)

    return stories, total_scanned


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@main_bp.route("/")
def index():
    return redirect(url_for("main.feed"))


@main_bp.route("/feed")
def feed():
    log.info("GET /feed")
    try:
        stories, total_scanned = _run_pipeline_global()
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
def feed_refresh():
    log.info("POST /feed/refresh")
    try:
        stories, total_scanned = _run_pipeline_global()
    except Exception as exc:
        log.error("feed refresh error: %s", exc)
        stories, total_scanned = [], 0
    return render_template(
        "feed_items.html",
        stories=stories,
        total_scanned=total_scanned,
    )


@main_bp.route("/preview")
def preview():
    log.info("GET /preview")
    settings_yaml = _load_settings_yaml()
    category_order = settings_yaml.get("digest", {}).get(
        "category_order", ["industry", "research", "tools", "policy"]
    )
    try:
        stories, total_scanned = _run_pipeline_global()
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
