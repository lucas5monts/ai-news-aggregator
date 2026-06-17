"""In-process APScheduler for the AI News Dashboard.

Jobs:
    1. hourly_refresh  — global story cache refresh (upserts into stories table)
    2. digest_check    — runs every minute; sends morning/evening digests to
                         users whose local time matches and have the edition enabled

Gating:
    - Only starts when ENABLE_SCHEDULER=1 env var is set
    - Guards against double-start from Flask dev-server reloader:
      only starts when WERKZEUG_RUN_MAIN=true (or when not using reloader)

Usage:
    from app.scheduler import init_scheduler
    init_scheduler(app)   # called from create_app()
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


# ------------------------------------------------------------------
# Predicate helpers
# ------------------------------------------------------------------


def is_users_morning(
    user_tz: str, time_str: str = "06:00", now_utc: datetime | None = None
) -> bool:
    """Return True if local time in *user_tz* matches *time_str* (default 6:00 AM)."""
    hour, minute = _parse_time_str(time_str)
    return _is_hour_minute(user_tz, hour=hour, minute=minute, now_utc=now_utc)


def is_users_evening(
    user_tz: str, time_str: str = "20:00", now_utc: datetime | None = None
) -> bool:
    """Return True if local time in *user_tz* matches *time_str* (default 8:00 PM)."""
    hour, minute = _parse_time_str(time_str)
    return _is_hour_minute(user_tz, hour=hour, minute=minute, now_utc=now_utc)


def _parse_time_str(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' → (hour, minute). Falls back to (6, 0) on bad input."""
    try:
        h, m = time_str.split(":")
        return int(h), int(m)
    except Exception:
        return 6, 0


def _is_hour_minute(
    user_tz: str, hour: int, minute: int, now_utc: datetime | None = None
) -> bool:
    """Return True if local time in *user_tz* is exactly *hour*:*minute*."""
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(user_tz)
    except Exception:
        log.warning("unknown timezone %r, falling back to UTC", user_tz)
        import zoneinfo
        tz = zoneinfo.ZoneInfo("UTC")

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    local = now_utc.astimezone(tz)
    return local.hour == hour and local.minute == minute


def _already_sent_today(user_id: int, edition: str, now_utc: datetime) -> bool:
    """Return True if a digest of this edition was already sent today for this user.

    'Today' is defined in UTC to keep the check simple and idempotent.
    """
    from .models import Digest, db

    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        db.session.query(Digest)
        .filter(
            Digest.user_id == user_id,
            Digest.edition == edition,
            Digest.sent_at >= today_start,
        )
        .count()
    )
    return count > 0


# ------------------------------------------------------------------
# Job implementations
# ------------------------------------------------------------------


def _hourly_refresh_job(app) -> None:
    """Pull all sources and upsert into the stories table."""
    with app.app_context():
        from pathlib import Path
        import yaml
        from core import fetch, pipeline, storage as core_storage

        log.info("scheduler: hourly refresh starting")
        sources_path = Path(app.root_path).parent / "config" / "sources.yaml"
        try:
            with sources_path.open() as f:
                cfg = yaml.safe_load(f)
            sources = cfg.get("sources", [])

            raw = fetch.fetch_all(sources)
            stories = pipeline.normalize(raw)

            db_path = Path(app.root_path).parent / "data.db"
            with core_storage.connect(db_path) as conn:
                inserted = core_storage.upsert_stories(conn, stories)
            log.info("scheduler: hourly refresh done — %d new stories", inserted)
        except Exception as exc:
            log.error("scheduler: hourly refresh failed: %s", exc)


def _digest_job(edition: str, app) -> None:
    """Send morning or evening digests to eligible users."""
    with app.app_context():
        from .models import Digest, DigestStory, User, UserSettings, db
        from pathlib import Path
        import yaml

        now_utc = datetime.now(timezone.utc)
        log.info("scheduler: digest check edition=%s at %s UTC", edition, now_utc.strftime("%H:%M"))

        check_fn = is_users_morning if edition == "morning" else is_users_evening

        users: list[User] = db.session.query(User).all()
        for user in users:
            settings = db.session.get(UserSettings, user.id)
            if settings is None:
                continue

            # Skip if email or this edition is disabled
            if not settings.send_email:
                continue
            attr = "morning_enabled" if edition == "morning" else "evening_enabled"
            if not getattr(settings, attr):
                continue

            # Check if it's their time
            time_str = settings.morning_time if edition == "morning" else settings.evening_time
            if not check_fn(settings.timezone, time_str=time_str, now_utc=now_utc):
                continue

            # Idempotency: don't double-send
            if _already_sent_today(user.id, edition, now_utc):
                log.info("scheduler: already sent %s digest to user_id=%s today", edition, user.id)
                continue

            _send_digest_for_user(
                user,
                settings,
                render_edition=edition,
                log_edition=edition,
                window_hours=24 if edition == "morning" else 12,
                send_time=time_str,
                now_utc=now_utc,
                app=app,
            )


def _custom_digest_job(app) -> None:
    """Send digests for user-defined custom times (beyond morning/evening)."""
    with app.app_context():
        from .models import User, UserDigestTime, UserSettings, db

        now_utc = datetime.now(timezone.utc)

        users: list[User] = db.session.query(User).all()
        for user in users:
            settings = db.session.get(UserSettings, user.id)
            if settings is None or not settings.send_email:
                continue

            custom_times = (
                db.session.query(UserDigestTime)
                .filter_by(user_id=user.id, enabled=True)
                .all()
            )
            for ct in custom_times:
                time_str = ct.send_time

                # Skip times already covered by an enabled preset to avoid
                # sending two digests at the same moment.
                if settings.morning_enabled and time_str == settings.morning_time:
                    continue
                if settings.evening_enabled and time_str == settings.evening_time:
                    continue

                if not _is_hour_minute(
                    settings.timezone,
                    *_parse_time_str(time_str),
                    now_utc=now_utc,
                ):
                    continue

                log_edition = f"custom@{time_str}"  # unique per time, fits VARCHAR(16)
                if _already_sent_today(user.id, log_edition, now_utc):
                    continue

                hour, _ = _parse_time_str(time_str)
                render_edition = "morning" if hour < 12 else "evening"
                _send_digest_for_user(
                    user,
                    settings,
                    render_edition=render_edition,
                    log_edition=log_edition,
                    window_hours=24 if render_edition == "morning" else 12,
                    send_time=time_str,
                    now_utc=now_utc,
                    app=app,
                )


def _send_digest_for_user(
    user,
    settings,
    *,
    render_edition: str,
    log_edition: str,
    window_hours: int,
    send_time: str,
    now_utc: datetime,
    app,
) -> None:
    """Run the full pipeline and send a digest for one user."""
    from pathlib import Path
    import yaml
    from .models import Digest, DigestStory, UserSource, UserTopic, db
    from core import fetch, pipeline, relevance
    from core.render import render_html, render_plaintext
    from core.deliver import build_subject, load_email_config, send_digest

    try:
        sources_path = Path(app.root_path).parent / "config" / "sources.yaml"
        settings_path = Path(app.root_path).parent / "config" / "settings.yaml"
        with sources_path.open() as f:
            sources_cfg = yaml.safe_load(f)
        with settings_path.open() as f:
            settings_yaml = yaml.safe_load(f)

        all_sources = sources_cfg.get("sources", [])
        user_source_rows = (
            db.session.query(UserSource).filter_by(user_id=user.id).all()
        )
        user_source_map = {r.source_name: r.enabled for r in user_source_rows}
        user_sources = [
            s for s in all_sources
            if user_source_map.get(s["name"], s.get("enabled", True))
        ]

        max_summary_chars = int(settings_yaml.get("digest", {}).get("max_summary_chars", 280))
        category_order = settings_yaml.get("digest", {}).get(
            "category_order",
            ["world", "us", "tech", "ai", "business", "science", "politics", "sports"],
        )
        llm_cfg = settings_yaml.get("llm", {}) or {}

        # Per-user interest topics drive LLM personalization (if any are set).
        user_topics = [
            t.topic for t in db.session.query(UserTopic).filter_by(user_id=user.id).all()
        ]

        raw = fetch.fetch_all(user_sources)
        total_scanned = len(raw)
        stories = pipeline.normalize(raw, max_summary_chars=max_summary_chars)
        # Age-window filter only; topic relevance is handled by the LLM below.
        stories = pipeline.filter_relevant(stories, [], window_hours)
        source_weights = {s["name"]: float(s.get("weight", 1.0)) for s in all_sources}
        stories = pipeline.rank(stories, source_weights)
        if user_topics:
            stories = relevance.score_stories_for_user(
                stories,
                user_topics,
                relevance_threshold=float(llm_cfg.get("relevance_threshold", 0.4)),
                max_stories_to_score=int(llm_cfg.get("max_stories_to_score", 50)),
                fallback_to_all=bool(llm_cfg.get("fallback_to_all", True)),
            )
        stories = pipeline.dedupe(stories)
        stories = pipeline.cap(stories, settings.max_stories)

        html = render_html(stories, edition=render_edition,
                           category_order=category_order, total_scanned=total_scanned)
        plaintext = render_plaintext(stories, edition=render_edition,
                                     category_order=category_order, total_scanned=total_scanned)
        subject = build_subject(render_edition, len(stories), send_time=send_time)

        cfg = load_email_config()
        base_url = os.environ.get("APP_BASE_URL", "http://localhost:8080").rstrip("/")
        unsubscribe_url = f"{base_url}/unsubscribe/{user.unsubscribe_token}"
        send_digest(
            subject=subject,
            plaintext=plaintext,
            html=html,
            to_address=user.email,
            from_address=cfg["GMAIL_ADDRESS"],
            app_password=cfg["GMAIL_APP_PASSWORD"],
            unsubscribe_url=unsubscribe_url,
        )

        # Log to DB
        digest = Digest(
            user_id=user.id,
            edition=log_edition,
            sent_at=now_utc,
            story_count=len(stories),
            subject=subject,
            html_blob=html,
        )
        db.session.add(digest)
        db.session.flush()
        for s in stories:
            db.session.add(DigestStory(digest_id=digest.id, story_id=s.id))
        db.session.commit()

        log.info(
            "scheduler: sent %s digest to user_id=%s (%d stories)",
            log_edition, user.id, len(stories)
        )
    except Exception as exc:
        log.error("scheduler: digest job failed for user_id=%s: %s", user.id, exc)
        db.session.rollback()


# ------------------------------------------------------------------
# Init
# ------------------------------------------------------------------


def init_scheduler(app) -> None:
    """Create and start the background scheduler (if enabled)."""
    global _scheduler

    if os.environ.get("ENABLE_SCHEDULER") != "1":
        log.info("scheduler: ENABLE_SCHEDULER != 1, skipping")
        return

    # Guard against Flask reloader spawning two schedulers
    reloader_active = os.environ.get("WERKZEUG_RUN_MAIN")
    if reloader_active is not None and reloader_active != "true":
        log.info("scheduler: not in main werkzeug process, skipping")
        return

    if _scheduler is not None and _scheduler.running:
        log.info("scheduler: already running")
        return

    _scheduler = BackgroundScheduler(timezone="UTC")

    # Job 1: hourly story refresh
    _scheduler.add_job(
        func=_hourly_refresh_job,
        trigger="interval",
        hours=1,
        id="hourly_refresh",
        args=[app],
        replace_existing=True,
    )

    # Job 2: morning digest — every minute
    _scheduler.add_job(
        func=_digest_job,
        trigger="cron",
        minute="*",
        id="morning_digest",
        args=["morning", app],
        replace_existing=True,
    )

    # Job 3: evening digest — every minute
    _scheduler.add_job(
        func=_digest_job,
        trigger="cron",
        minute="*",
        id="evening_digest",
        args=["evening", app],
        replace_existing=True,
    )

    # Job 4: custom user-defined times — every minute
    _scheduler.add_job(
        func=_custom_digest_job,
        trigger="cron",
        minute="*",
        id="custom_digest",
        args=[app],
        replace_existing=True,
    )

    _scheduler.start()
    log.info("scheduler: started (hourly refresh + per-minute digest checks)")
