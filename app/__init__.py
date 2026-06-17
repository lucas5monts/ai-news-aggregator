"""Flask application factory for the AI News Dashboard."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager

log = logging.getLogger(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)

login_manager = LoginManager()


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        test_config: Optional dict of config overrides (used in tests).
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # --- Config -----------------------------------------------------------
    flask_env = os.environ.get("FLASK_ENV", "development")

    secret_key = os.environ.get("SECRET_KEY", "")
    if flask_env == "production":
        if not secret_key or secret_key in ("dev-secret-change-me", "change-me-to-a-long-random-string"):
            raise RuntimeError(
                "SECRET_KEY env var is not set or is still the default placeholder. "
                "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
    app.config["SECRET_KEY"] = secret_key or "dev-secret-change-me"

    # DATABASE_URL: default SQLite; handle Heroku-style postgres:// URLs
    raw_db_url = os.environ.get("DATABASE_URL", "")
    if raw_db_url.startswith("postgres://"):
        raw_db_url = "postgresql+psycopg2://" + raw_db_url[len("postgres://"):]
    if not raw_db_url:
        raw_db_url = "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = raw_db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB

    app.config["FLASK_ENV"] = flask_env
    if flask_env == "production":
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    if test_config:
        app.config.update(test_config)

    # --- Extensions -------------------------------------------------------
    from .models import db
    db.init_app(app)

    limiter.init_app(app)

    # CSRF — must come after test_config is applied so WTF_CSRF_ENABLED=False
    # in test fixtures is already in app.config before CSRFProtect initialises.
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect()
    # Belt-and-suspenders: explicitly honour the test-config opt-out key.
    if test_config and test_config.get("WTF_CSRF_ENABLED") is False:
        app.config["WTF_CSRF_ENABLED"] = False
    csrf.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User
        return db.session.get(User, int(user_id))

    # --- Blueprints -------------------------------------------------------
    from .auth import auth_bp
    from .subscriptions import subscriptions_bp
    from .routes import main_bp
    from .preferences import preferences_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(preferences_bp)

    from .template_filters import card_image, placeholder_image, time_ago, safe_url
    app.jinja_env.filters["time_ago"] = time_ago
    app.jinja_env.filters["card_image"] = card_image
    app.jinja_env.filters["safe_url"] = safe_url
    app.jinja_env.filters["placeholder_image"] = placeholder_image

    # --- Security headers -------------------------------------------------
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if flask_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP: allow scripts only from known CDNs (tailwind, htmx, lucide, fonts)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "frame-src 'none';"
        )
        return response

    # --- DB init ----------------------------------------------------------
    with app.app_context():
        db.create_all()
        _run_migrations(db)

    # --- Scheduler --------------------------------------------------------
    from .scheduler import init_scheduler
    init_scheduler(app)

    log.info("create_app: app created (env=%s db=%s)", flask_env, raw_db_url)
    return app


def _run_migrations(db) -> None:
    """Idempotent schema migrations for existing databases."""
    _migrate_drop_sent_at(db)
    _migrate_create_user_topics(db)
    _migrate_add_max_categories(db)
    _migrate_add_digest_times(db)
    _migrate_create_user_digest_times(db)
    _migrate_add_unsubscribe_token(db)
    _migrate_add_password_hash(db)


def _migrate_add_password_hash(db) -> None:
    """Add password_hash column to users if missing."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result]
            if not cols:
                return
            if "password_hash" in cols:
                return
            conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"))
            conn.commit()
            log.info("migration: added users.password_hash")
    except Exception as exc:
        log.debug("migration _migrate_add_password_hash: %s (skipping)", exc)


def _migrate_create_user_topics(db) -> None:
    """Create the user_topics table on existing installs.

    db.create_all() already handles this, but we keep an explicit guard for
    non-ORM-managed databases / belt-and-suspenders.
    """
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_topics (
                    user_id    INTEGER NOT NULL,
                    topic      VARCHAR(128) NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (user_id, topic),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_user_topics: %s (skipping)", exc)


def _migrate_add_max_categories(db) -> None:
    """Add user_settings.max_categories to existing databases if missing."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(user_settings)"))
            columns = [row[1] for row in result]
            if not columns:
                return  # table doesn't exist yet (fresh install handled by create_all)
            if "max_categories" in columns:
                return
            conn.execute(text("ALTER TABLE user_settings ADD COLUMN max_categories INTEGER"))
            conn.commit()
            log.info("migration: added user_settings.max_categories")
    except Exception as exc:
        # Non-SQLite DB or fresh install — no-op
        log.debug("migration _migrate_add_max_categories: %s (skipping)", exc)


def _migrate_add_digest_times(db) -> None:
    """Add morning_time and evening_time columns to user_settings if missing."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(user_settings)"))
            cols = [row[1] for row in result]
            if not cols:
                return  # table doesn't exist yet (fresh install handled by create_all)
            if "morning_time" not in cols:
                conn.execute(text("ALTER TABLE user_settings ADD COLUMN morning_time TEXT NOT NULL DEFAULT '06:00'"))
            if "evening_time" not in cols:
                conn.execute(text("ALTER TABLE user_settings ADD COLUMN evening_time TEXT NOT NULL DEFAULT '20:00'"))
            conn.commit()
    except Exception as exc:
        log.debug("_migrate_add_digest_times: %s (skipping)", exc)


def _migrate_create_user_digest_times(db) -> None:
    """Create the user_digest_times table on existing installs.

    db.create_all() handles fresh installs; this is a belt-and-suspenders guard
    for databases created before custom delivery times existed.
    """
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_digest_times (
                    user_id   INTEGER NOT NULL,
                    send_time VARCHAR(5) NOT NULL,
                    enabled   BOOLEAN NOT NULL DEFAULT 1,
                    PRIMARY KEY (user_id, send_time),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_user_digest_times: %s (skipping)", exc)


def _migrate_add_unsubscribe_token(db) -> None:
    """Add users.unsubscribe_token to existing databases and back-fill tokens."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result]
            if not cols:
                return  # table doesn't exist yet (fresh install handled by create_all)
            if "unsubscribe_token" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN unsubscribe_token TEXT"))
                # Back-fill tokens for existing users (64 hex chars).
                conn.execute(text(
                    "UPDATE users SET unsubscribe_token = hex(randomblob(32)) "
                    "WHERE unsubscribe_token IS NULL"
                ))
                conn.commit()
                log.info("migration: added users.unsubscribe_token")
    except Exception as exc:
        log.debug("migration _migrate_add_unsubscribe_token: %s (skipping)", exc)


def _migrate_drop_sent_at(db) -> None:
    """Drop the sent_at column from stories table if it exists (new schema omits it).

    SQLite does not support DROP COLUMN before 3.35.0; we handle both cases.
    """
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(stories)"))
            columns = [row[1] for row in result]
            if "sent_at" not in columns:
                return  # already migrated or fresh install
            # SQLite >= 3.35.0 supports DROP COLUMN
            try:
                conn.execute(text("ALTER TABLE stories DROP COLUMN sent_at"))
                conn.commit()
                log.info("migration: dropped stories.sent_at")
            except Exception:
                # Older SQLite: create new table without the column
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS stories_new (
                        id           TEXT PRIMARY KEY,
                        title        TEXT NOT NULL,
                        url          TEXT NOT NULL,
                        summary      TEXT NOT NULL,
                        source_name  TEXT NOT NULL,
                        category     TEXT NOT NULL,
                        published_at TEXT NOT NULL,
                        score        REAL NOT NULL,
                        first_seen   TEXT NOT NULL
                    )
                """))
                conn.execute(text("""
                    INSERT OR IGNORE INTO stories_new
                        SELECT id, title, url, summary, source_name, category,
                               published_at, score, first_seen
                        FROM stories
                """))
                conn.execute(text("DROP TABLE stories"))
                conn.execute(text("ALTER TABLE stories_new RENAME TO stories"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_stories_published ON stories(published_at)"))
                conn.commit()
                log.info("migration: rebuilt stories table without sent_at (SQLite compat)")
    except Exception as exc:
        # Non-SQLite DB or fresh install — no-op
        log.debug("migration _migrate_drop_sent_at: %s (skipping)", exc)

