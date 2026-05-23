"""Magic-link authentication for the AI News Dashboard.

Flow:
    1. User enters email at /login  → POST /login calls send_magic_link()
    2. Magic link email is sent with a signed token URL (/auth/<token>)
    3. User clicks link  → GET /auth/<token> calls consume_token()
    4. On success: user is logged in via Flask-Login, redirected to /feed

Rate limiting: max 3 magic links per email per 10-minute window (checked in DB).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader

import secrets

from core.deliver import load_email_config, send_digest
from .models import MagicLink, User, UserSettings, UserSource, db

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)
login_manager = LoginManager()


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is UTC-aware (SQLite may return naive datetimes)."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ------------------------------------------------------------------
# Flask-Login wiring
# ------------------------------------------------------------------


def init_login_manager(app) -> None:  # called from create_app()
    login_manager.login_view = "auth.login"  # type: ignore[assignment]
    login_manager.login_message = "Please sign in to access that page."
    login_manager.login_message_category = "info"
    login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


# ------------------------------------------------------------------
# Core auth helpers
# ------------------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def send_magic_link(email: str) -> bool | None:
    """Create a signed magic-link token and email it to *email*.

    Returns:
        True   — link created and email sent successfully.
        False  — rate-limited (>= 3 attempts in last 10 minutes).
        None   — SMTP send failed. The DB row is cleaned up so this
                 attempt does NOT count toward the rate limit; the
                 caller can retry immediately. We clean up rather than
                 marking the row "failed" to keep the schema simple.
    """
    email = email.strip().lower()

    # Rate limit: max 3 links per email in the last 10 minutes
    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    recent_count = (
        db.session.query(MagicLink)
        .filter(
            MagicLink.email == email,
            MagicLink.created_at >= ten_min_ago,
        )
        .count()
    )
    if recent_count >= 3:
        log.warning("rate limit: email=%s sent %d links in last 10 min", email, recent_count)
        return False

    # Ensure user exists (sign-up on first magic link)
    user = db.session.query(User).filter(
        db.func.lower(User.email) == email
    ).first()
    if user is None:
        user = User(email=email)
        db.session.add(user)
        db.session.flush()  # get user.id without committing yet
        # Seed default settings + sources
        _seed_user_defaults(user)

    # Generate signed token (nonce ensures uniqueness even within the same second)
    token = _serializer().dumps({"email": email, "nonce": secrets.token_hex(8)})

    now = datetime.now(timezone.utc)
    magic_link = MagicLink(
        token=token,
        email=email,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    db.session.add(magic_link)
    db.session.commit()

    # Build the login URL
    login_url = url_for("auth.consume_magic_link", token=token, _external=True)

    # Render the email body
    template_dir = Path(__file__).parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    html_body = env.get_template("emails/magic_link.html").render(
        login_url=login_url,
        email=email,
        expires_minutes=15,
    )

    try:
        cfg = load_email_config()
        send_digest(
            subject="Sign in to AI News Dashboard",
            plaintext=f"Click this link to sign in:\n{login_url}\n\nIt expires in 15 minutes.",
            html=html_body,
            to_address=email,
            from_address=cfg["GMAIL_ADDRESS"],
            app_password=cfg["GMAIL_APP_PASSWORD"],
        )
        log.info("magic link sent to %s", email)
        return True
    except Exception as exc:
        log.error("failed to send magic link to %s: %s", email, exc)
        # Delete the DB row so this failed attempt does NOT count toward the
        # rate limit — the user should be able to retry immediately.
        # (All users already exist after their first request, so there is no
        # email-enumeration risk in returning a distinct None sentinel here.)
        try:
            db.session.delete(magic_link)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return None


def consume_token(token: str) -> User | None:
    """Validate *token*, mark it used, update last_login_at, return the User.

    Returns None on any error (expired, tampered, already used).
    """
    # 1. Verify signature + age (15-minute TTL)
    try:
        data = _serializer().loads(token, max_age=900)  # 900s = 15 min
    except SignatureExpired:
        log.info("consume_token: token expired")
        return None
    except BadSignature:
        log.warning("consume_token: bad signature")
        return None

    email = data.get("email", "").strip().lower()
    if not email:
        return None

    # 2. Look up the DB row
    row = db.session.get(MagicLink, token)
    if row is None:
        log.warning("consume_token: token not found in DB")
        return None
    if row.used_at is not None:
        log.warning("consume_token: replay attack — token already used at %s", row.used_at)
        return None

    now = datetime.now(timezone.utc)
    # SQLite may return naive datetimes; normalise before comparing
    expires_at = _ensure_utc(row.expires_at)
    if expires_at < now:
        log.info("consume_token: DB-level expiry check failed")
        return None

    # 3. Mark used
    row.used_at = now
    db.session.add(row)

    # 4. Update user
    user = db.session.query(User).filter(
        db.func.lower(User.email) == email
    ).first()
    if user is None:
        log.error("consume_token: user disappeared for email=%s", email)
        db.session.rollback()
        return None

    user.last_login_at = now
    db.session.add(user)
    db.session.commit()

    log.info("consume_token: success for user_id=%s email=%s", user.id, email)
    return user


def _seed_user_defaults(user: User) -> None:
    """Create default UserSettings and enable all sources from sources.yaml."""
    import yaml

    # Settings
    settings = UserSettings(user_id=user.id)
    db.session.add(settings)

    # Sources
    sources_path = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"
    try:
        with sources_path.open() as f:
            cfg = yaml.safe_load(f)
        for src in cfg.get("sources", []):
            us = UserSource(
                user_id=user.id,
                source_name=src["name"],
                enabled=src.get("enabled", True),
            )
            db.session.add(us)
    except Exception as exc:
        log.warning("could not seed user sources: %s", exc)


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
            return render_template("login.html"), 400

        ok = send_magic_link(email)
        if ok is None:
            # SMTP failure — transient server-side error, not rate-limit
            flash(
                "Couldn't send the sign-in email right now. Please try again in a moment.",
                "error",
            )
            return render_template("login.html"), 500
        if ok is False:
            # Rate-limited
            flash(
                "Too many sign-in requests. Please wait 10 minutes and try again.",
                "error",
            )
            return render_template("login.html"), 429

        flash(
            f"Check your inbox at {email} for a sign-in link. It expires in 15 minutes.",
            "success",
        )
        return redirect(url_for("auth.login"))

    return render_template("login.html")


@auth_bp.route("/auth/<token>")
def consume_magic_link(token: str):
    user = consume_token(token)
    if user is None:
        flash(
            "That sign-in link is invalid or has expired. Please request a new one.",
            "error",
        )
        return redirect(url_for("auth.login"))

    login_user(user, remember=True)
    log.info("login: user_id=%s", user.id)
    next_url = request.args.get("next") or url_for("main.feed")
    return redirect(next_url)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    log.info("logout: user_id=%s", current_user.id)
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
