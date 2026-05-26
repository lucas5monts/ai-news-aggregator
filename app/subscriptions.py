"""Newsletter subscription — no login required."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml
from flask import Blueprint, flash, redirect, render_template, request, url_for

from .models import User, UserSettings, UserSource, db

log = logging.getLogger(__name__)

subscriptions_bp = Blueprint("subscriptions", __name__)


def _seed_user_defaults(user: User) -> None:
    """Create default UserSettings and enable all sources from sources.yaml."""
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
) -> User:
    """Create or update a subscriber. Enables email delivery."""
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
    db.session.commit()
    return user


@subscriptions_bp.route("/subscribe", methods=["GET", "POST"])
def subscribe():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
            return render_template("subscribe.html"), 400

        morning = "morning_enabled" in request.form
        evening = "evening_enabled" in request.form
        timezone = request.form.get("timezone", "America/Los_Angeles").strip()

        try:
            user = subscribe_email(
                email,
                morning_enabled=morning,
                evening_enabled=evening,
                timezone=timezone or "America/Los_Angeles",
            )
            log.info("subscribed user_id=%s email=%s", user.id, email)
            flash(f"You're subscribed! Digests will be sent to {email}.", "success")
            return redirect(url_for("main.feed"))
        except Exception as exc:
            log.error("subscribe failed for %s: %s", email, exc)
            db.session.rollback()
            flash("Something went wrong. Please try again.", "error")
            return render_template("subscribe.html"), 500

    return render_template("subscribe.html")
