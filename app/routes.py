"""Main application routes for the AI News Dashboard.

All routes are public — no login required. Subscribers sign up via /subscribe.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import limiter
from app.models import db

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


def _load_categories() -> list[str]:
    """Category display order for the public feed (from settings.yaml)."""
    settings_yaml = _load_settings_yaml()
    return settings_yaml.get("digest", {}).get(
        "category_order",
        ["world", "us", "tech", "ai", "business", "science", "politics", "sports"],
    )


def _build_ai_metadata(stories, total_scanned: int) -> dict:
    topics_active = sorted({s.matched_topic for s in stories if s.matched_topic})
    return {
        "personalized": bool(topics_active),
        "total_scored": total_scanned,
        "topics_active": topics_active,
        "kept": len(stories),
    }


def _build_topic_counts(stories) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for s in stories:
        if s.matched_topic:
            counts[s.matched_topic] = counts.get(s.matched_topic, 0) + 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _empty_ai_metadata() -> dict:
    return {
        "personalized": False,
        "total_scored": 0,
        "topics_active": [],
        "kept": 0,
    }


def _run_pipeline_global(category: str | None = None) -> tuple[list, int, dict]:
    """Fetch + pipeline using global config defaults.

    When a subscriber cookie is present and the user has interest topics,
    stories are scored by the LLM for personalization metadata (matched_topic,
    llm_score). Otherwise the feed is unfiltered by topic.
    An optional *category* narrows results to a single source_category.
    """
    from app.models import UserTopic
    from app.subscriber_cookie import get_subscriber_user
    from flask_login import current_user
    from core import fetch, pipeline, relevance

    all_sources = _load_sources_yaml()
    settings_yaml = _load_settings_yaml()

    user_sources = [s for s in all_sources if s.get("enabled", True)]

    max_summary_chars = int(settings_yaml.get("digest", {}).get("max_summary_chars", 280))
    max_stories = int(settings_yaml.get("max_stories", 15))
    window_hours = int(settings_yaml.get("default_time_window_hours", 24))
    llm_cfg = settings_yaml.get("llm", {}) or {}

    raw = fetch.fetch_all(user_sources)
    total_scanned = len(raw)

    stories = pipeline.normalize(raw, max_summary_chars=max_summary_chars)
    stories = pipeline.filter_relevant(stories, [], window_hours)
    stories = pipeline.filter_junk(stories)

    source_weights = {s["name"]: float(s.get("weight", 1.0)) for s in all_sources}
    stories = pipeline.rank(stories, source_weights)
    stories = pipeline.dedupe(stories)

    user = current_user if current_user.is_authenticated else get_subscriber_user()
    if user:
        user_topics = [
            t.topic for t in db.session.query(UserTopic).filter_by(user_id=user.id).all()
        ]
        if user_topics:
            stories = relevance.score_stories_for_user(
                stories,
                user_topics,
                relevance_threshold=float(llm_cfg.get("relevance_threshold", 0.4)),
                max_stories_to_score=int(llm_cfg.get("max_stories_to_score", 50)),
                fallback_to_all=bool(llm_cfg.get("fallback_to_all", True)),
            )

    if category:
        stories = [s for s in stories if s.source_category == category]

    stories = pipeline.cap(stories, max_stories)

    from core.images import enrich_story_images
    stories = enrich_story_images(stories)

    return stories, total_scanned, _build_ai_metadata(stories, total_scanned)


def _run_pipeline_filtered(
    source_names: list[str],
    window_hours: int,
    max_stories: int,
    categories: list[str],
) -> tuple[list, int]:
    """Run the pipeline with user-selected sources, window, categories, and cap."""
    from core import fetch, pipeline

    all_sources = _load_sources_yaml()
    settings_yaml = _load_settings_yaml()

    user_sources = [
        s for s in all_sources
        if s.get("enabled", True) and s["name"] in source_names
    ]

    keywords = settings_yaml.get("relevance_keywords") or []
    max_summary_chars = int(settings_yaml.get("digest", {}).get("max_summary_chars", 280))

    raw = fetch.fetch_all(user_sources)
    total_scanned = len(raw)

    stories = pipeline.normalize(raw, max_summary_chars=max_summary_chars)
    stories = pipeline.filter_relevant(stories, keywords, window_hours)

    source_weights = {s["name"]: float(s.get("weight", 1.0)) for s in all_sources}
    stories = pipeline.rank(stories, source_weights)
    stories = pipeline.dedupe(stories)

    if categories:
        stories = [s for s in stories if s.source_category in categories]

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


def _selected_category() -> str | None:
    """Validated ?category= query param, or None for all categories."""
    cat = request.args.get("category")
    return cat if cat in _load_categories() else None


@main_bp.route("/feed")
def feed():
    log.info("GET /feed")
    category = _selected_category()
    try:
        stories, total_scanned, ai_meta = _run_pipeline_global(category)
    except Exception as exc:
        log.error("feed pipeline error: %s", exc)
        stories, total_scanned, ai_meta = [], 0, _empty_ai_metadata()
        flash("Could not fetch stories. Check your internet connection.", "error")
    return render_template(
        "feed.html",
        stories=stories,
        total_scanned=total_scanned,
        ai_meta=ai_meta,
        topic_counts=_build_topic_counts(stories),
        categories=_load_categories(),
        selected_category=category,
    )


@main_bp.route("/feed/refresh", methods=["POST"])
@limiter.limit("2 per minute")
def feed_refresh():
    log.info("POST /feed/refresh")
    category = _selected_category()
    try:
        stories, total_scanned, ai_meta = _run_pipeline_global(category)
    except Exception as exc:
        log.error("feed refresh error: %s", exc)
        stories, total_scanned, ai_meta = [], 0, _empty_ai_metadata()
    return render_template(
        "feed_items.html",
        stories=stories,
        total_scanned=total_scanned,
        ai_meta=ai_meta,
        topic_counts=_build_topic_counts(stories),
    )


@main_bp.route("/preview")
def preview():
    log.info("GET /preview")
    settings_yaml = _load_settings_yaml()
    all_sources = _load_sources_yaml()
    category_order = settings_yaml.get("digest", {}).get(
        "category_order", ["industry", "research", "tools", "policy"]
    )

    available_sources = [s for s in all_sources if s.get("enabled", True)]
    available_source_names = [s["name"] for s in available_sources]
    available_categories = category_order

    default_window = int(settings_yaml.get("default_time_window_hours", 24))
    default_max = int(settings_yaml.get("max_stories", 15))

    # Read filters from query string (fall back to "everything" defaults)
    sel_cats = [c for c in request.args.getlist("category") if c in available_categories]
    if not sel_cats:
        sel_cats = list(available_categories)

    sel_sources = [s for s in request.args.getlist("source") if s in available_source_names]
    if not sel_sources:
        sel_sources = list(available_source_names)

    try:
        window_hours = int(request.args.get("window_hours", default_window))
    except (TypeError, ValueError):
        window_hours = default_window
    try:
        max_stories = int(request.args.get("max_stories", default_max))
    except (TypeError, ValueError):
        max_stories = default_max
    max_stories = max(1, min(max_stories, 50))

    try:
        stories, total_scanned = _run_pipeline_filtered(
            sel_sources, window_hours, max_stories, sel_cats
        )
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
        available_sources=available_sources,
        available_categories=available_categories,
        sel_cats=sel_cats,
        sel_sources=sel_sources,
        window_hours=window_hours,
        max_stories=max_stories,
    )
