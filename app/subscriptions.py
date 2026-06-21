"""Subscribe / unsubscribe routes and helper functions."""
from __future__ import annotations

import logging
import re
import threading
import zoneinfo
from pathlib import Path

import yaml
from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for
from flask_login import login_user

from app import limiter
from .subscriber_cookie import clear_subscriber_cookie, set_subscriber_cookie
from .models import User, UserDigestTime, UserSettings, UserSource, UserTopic, db

log = logging.getLogger(__name__)

subscriptions_bp = Blueprint("subscriptions", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VALID_TIMEZONES = zoneinfo.available_timezones()
DEFAULT_TZ = "America/Los_Angeles"
_MIN_PASSWORD_LEN = 8
_MAX_PASSWORD_LEN = 128

MAX_TOPICS = 20
MAX_TOPIC_LEN = 80
MAX_CUSTOM_TIMES = 10

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# safe topic chars: letters/numbers/spaces/hyphens/etc. Blocks angle brackets,
# slashes, colons — prompt injection vectors since topics go into LLM prompts.
_TOPIC_SAFE_RE = re.compile(r"^[\w\s\-&'.,!]+$", re.UNICODE)


def _parse_form_time(raw: str, fallback: str) -> str:
    """Validate 'HH:MM' (24-hour) format and return it, or return fallback."""
    raw = (raw or "").strip()
    if _TIME_RE.match(raw):
        return raw
    return fallback


def parse_times(raw_times: list[str]) -> list[str]:
    """Validate, dedupe, sort, and cap a list of raw HH:MM strings."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in raw_times or []:
        t = (raw or "").strip()
        if not _TIME_RE.match(t) or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= MAX_CUSTOM_TIMES:
            break
    return sorted(out)


def set_user_digest_times(user: User, raw_times: list[str]) -> None:
    """Overwrite all custom delivery times for a user."""
    times = parse_times(raw_times)
    db.session.query(UserDigestTime).filter_by(user_id=user.id).delete()
    for t in times:
        db.session.add(UserDigestTime(user_id=user.id, send_time=t, enabled=True))


def parse_topics(raw_text: str) -> list[str]:
    """Parse comma/newline-separated interest topics: strip, dedupe, validate, cap."""
    if not raw_text:
        return []
    parts = re.split(r"[,\n\r]+", raw_text)
    seen: set[str] = set()
    topics: list[str] = []
    for part in parts:
        topic = part.strip()[:MAX_TOPIC_LEN].strip()
        if not topic:
            continue
        # reject prompt-injection-style content before it hits an LLM
        if not _TOPIC_SAFE_RE.match(topic):
            log.warning("parse_topics: rejected suspicious topic %r", topic[:40])
            continue
        key = topic.lower()
        if key in seen:
            continue
        seen.add(key)
        topics.append(topic)
        if len(topics) >= MAX_TOPICS:
            break
    return topics


def set_user_topics(user: User, raw_text: str) -> None:
    """Overwrite all interest topics for a user."""
    topics = parse_topics(raw_text)
    db.session.query(UserTopic).filter_by(user_id=user.id).delete()
    for topic in topics:
        db.session.add(UserTopic(user_id=user.id, topic=topic))


def _seed_user_defaults(user: User) -> None:
    """Bootstrap UserSettings + UserSource rows from sources.yaml for a new user."""
    settings = UserSettings(user_id=user.id)
    db.session.add(settings)

    sources_path = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
    try:
        with sources_path.open() as f:
            cfg = yaml.safe_load(f)
        for src in cfg.get("sources", []):
            db.session.add(
                UserSource(
                    user_id=user.id,
                    source_name=src["name"],
                    enabled=src.get("enabled", True),
                )
            )
    except Exception as exc:
        log.warning("could not seed user sources: %s", exc)


def subscribe_email(
    email: str,
    *,
    morning_enabled: bool = True,
    evening_enabled: bool = False,
    timezone: str = "America/Los_Angeles",
    morning_time: str = "06:00",
    evening_time: str = "20:00",
) -> User:
    """Upsert a subscriber row and flip send_email=True."""
    email = email.strip().lower()

    user = db.session.query(User).filter(db.func.lower(User.email) == email).first()
    if user is None:
        user = User(email=email)
        db.session.add(user)
        db.session.flush()
        _seed_user_defaults(user)

    settings = db.session.get(UserSettings, user.id)
    if settings is None:
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)

    settings.send_email = True
    settings.morning_enabled = morning_enabled
    settings.evening_enabled = evening_enabled
    settings.timezone = timezone or "America/Los_Angeles"
    settings.morning_time = morning_time
    settings.evening_time = evening_time
    db.session.commit()
    return user


@subscriptions_bp.route("/subscribe", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour")
def subscribe():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or len(email) > 254 or not _EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
            return render_template("subscribe.html", initial_times=[]), 400

        existing = db.session.query(User).filter(
            db.func.lower(User.email) == email
        ).first()
        if existing:
            # neutral redirect — avoid confirming whether the address is registered
            flash(
                "If that address is registered, you can log in to manage your preferences.",
                "info",
            )
            return redirect(url_for("auth.login"))

        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < _MIN_PASSWORD_LEN:
            flash(f"Password must be at least {_MIN_PASSWORD_LEN} characters.", "error")
            return render_template(
                "subscribe.html",
                initial_times=parse_times(request.form.getlist("custom_times")),
            ), 400
        if len(password) > _MAX_PASSWORD_LEN:
            flash(f"Password must be {_MAX_PASSWORD_LEN} characters or fewer.", "error")
            return render_template(
                "subscribe.html",
                initial_times=parse_times(request.form.getlist("custom_times")),
            ), 400
        if password != confirm:
            flash("Passwords don't match.", "error")
            return render_template(
                "subscribe.html",
                initial_times=parse_times(request.form.getlist("custom_times")),
            ), 400

        morning = "morning_enabled" in request.form
        evening = "evening_enabled" in request.form
        timezone = request.form.get("timezone", DEFAULT_TZ).strip()
        if timezone not in VALID_TIMEZONES:
            timezone = DEFAULT_TZ
        morning_time = _parse_form_time(request.form.get("morning_time", ""), "06:00")
        evening_time = _parse_form_time(request.form.get("evening_time", ""), "20:00")

        try:
            user = subscribe_email(
                email,
                morning_enabled=morning,
                evening_enabled=evening,
                timezone=timezone or "America/Los_Angeles",
                morning_time=morning_time,
                evening_time=evening_time,
            )
            user.set_password(password)
            set_user_topics(user, request.form.get("topics", ""))
            set_user_digest_times(user, request.form.getlist("custom_times"))
            db.session.commit()
            login_user(user)

            # check referral cookie and assign referrer
            ref_code = request.cookies.get("referral_code", "")
            if ref_code:
                referrer = db.session.query(User).filter_by(referral_code=ref_code).first()
                if referrer and referrer.id != user.id:
                    user.referred_by_id = referrer.id
                    db.session.commit()

            # send welcome email in background so it doesn't block the response
            from app.onboarding import send_welcome_email
            from flask import current_app
            _app = current_app._get_current_object()
            threading.Thread(target=send_welcome_email, args=(user, _app), daemon=True).start()

            log.info("subscribed user_id=%s email=%s", user.id, email)
            flash(f"You're subscribed! Digests will be sent to {email}.", "success")
            resp = make_response(redirect(url_for("main.feed")))
            set_subscriber_cookie(resp, user.id)
            resp.delete_cookie("referral_code")
            return resp
        except Exception as exc:
            log.error("subscribe failed for %s: %s", email, exc)
            db.session.rollback()
            flash("Something went wrong. Please try again.", "error")
            return render_template("subscribe.html", initial_times=[]), 500

    return render_template("subscribe.html", initial_times=[])


@subscriptions_bp.route("/ref/<code>")
@limiter.limit("30 per minute")
def referral_landing(code: str):
    """Set a cookie recording who referred this visitor, then redirect to subscribe."""
    resp = make_response(redirect(url_for("subscriptions.subscribe")))
    resp.set_cookie("referral_code", code, max_age=60 * 60 * 24 * 7, httponly=True, samesite="Lax")
    return resp


@subscriptions_bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def unsubscribe(token: str):
    user = db.session.query(User).filter_by(unsubscribe_token=token).first()
    if user is None:
        flash("Invalid or expired unsubscribe link.", "error")
        return render_template("unsubscribe.html", valid=False), 404

    if request.method == "POST":
        settings = db.session.get(UserSettings, user.id)
        if settings:
            settings.send_email = False
        db.session.commit()
        log.info("unsubscribed user_id=%s via token", user.id)
        resp = make_response(render_template("unsubscribe.html", valid=True, done=True))
        clear_subscriber_cookie(resp)
        return resp

    return render_template("unsubscribe.html", valid=True, done=False, email=user.email)
