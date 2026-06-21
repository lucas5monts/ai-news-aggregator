"""Flask app factory."""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from flask import Flask, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager

log = logging.getLogger(__name__)

def _limiter_storage_uri() -> str:
    """Redis in prod, in-memory otherwise."""
    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        return redis_url
    return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=_limiter_storage_uri(),
)

login_manager = LoginManager()


def create_app(test_config: dict | None = None) -> Flask:
    """App factory. Pass test_config to override settings in tests."""
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # --- config ---
    flask_env = os.environ.get("FLASK_ENV", "development")

    secret_key = os.environ.get("SECRET_KEY", "")
    if flask_env == "production":
        if not secret_key or secret_key in ("dev-secret-change-me", "change-me-to-a-long-random-string"):
            raise RuntimeError(
                "SECRET_KEY env var is not set or is still the default placeholder. "
                "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
            )
    app.config["SECRET_KEY"] = secret_key or "dev-secret-change-me"

    # handle Heroku-style postgres:// → postgresql+psycopg2://
    raw_db_url = os.environ.get("DATABASE_URL", "")
    if raw_db_url.startswith("postgres://"):
        raw_db_url = "postgresql+psycopg2://" + raw_db_url[len("postgres://"):]
    if not raw_db_url:
        raw_db_url = "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = raw_db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB

    app.config["FLASK_ENV"] = flask_env
    secure_cookies = (
        flask_env == "production"
        or os.environ.get("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"}
        or os.environ.get("APP_BASE_URL", "").startswith("https://")
    )
    if secure_cookies:
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["SESSION_COOKIE_HTTPONLY"] = True
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    if test_config:
        app.config.update(test_config)

    # --- extensions ---
    from .models import db
    db.init_app(app)

    limiter.init_app(app)

    # CSRFProtect must init after test_config so WTF_CSRF_ENABLED=False takes effect
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect()
    # honour the explicit opt-out key too
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

    # --- blueprints ---
    from .auth import auth_bp
    from .subscriptions import subscriptions_bp
    from .routes import main_bp
    from .preferences import preferences_bp
    from .bookmarks import bookmarks_bp
    from .digest_archive import digest_archive_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(preferences_bp)
    app.register_blueprint(bookmarks_bp)
    app.register_blueprint(digest_archive_bp)

    from .template_filters import card_image, placeholder_image, reading_time, time_ago, safe_url
    app.jinja_env.filters["time_ago"] = time_ago
    app.jinja_env.filters["card_image"] = card_image
    app.jinja_env.filters["safe_url"] = safe_url
    app.jinja_env.filters["placeholder_image"] = placeholder_image
    app.jinja_env.filters["reading_time"] = reading_time

    # --- security headers ---
    @app.before_request
    def set_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def inject_security_context():
        return {"csp_nonce": lambda: getattr(g, "csp_nonce", "")}

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{getattr(g, 'csp_nonce', '')}' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "frame-src 'self'; "
        )
        if secure_cookies:
            csp += "upgrade-insecure-requests; "
        response.headers["Content-Security-Policy"] = csp
        return response

    # --- db init ---
    with app.app_context():
        db.create_all()
        _run_migrations(db)

    # --- scheduler ---
    from .scheduler import init_scheduler
    init_scheduler(app)

    log.info("create_app: app created (env=%s db=%s)", flask_env, raw_db_url)
    return app


def _run_migrations(db) -> None:
    """Run all schema migrations in order. Each one is a no-op if already applied."""
    _migrate_drop_sent_at(db)
    _migrate_create_user_topics(db)
    _migrate_add_max_categories(db)
    _migrate_add_digest_times(db)
    _migrate_create_user_digest_times(db)
    _migrate_add_unsubscribe_token(db)
    _migrate_add_password_hash(db)
    _migrate_create_stories_fts(db)
    _migrate_create_user_bookmarks(db)
    _migrate_create_story_clicks(db)
    _migrate_create_user_blocked_keywords(db)
    _migrate_create_user_custom_sources(db)
    _migrate_create_onboarding_emails(db)
    _migrate_add_referral_fields(db)


def _migrate_add_password_hash(db) -> None:
    """users.password_hash — added post-launch."""
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
    """Belt-and-suspenders: create user_topics if db.create_all() missed it."""
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
    """user_settings.max_categories — added post-launch."""
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
        # non-SQLite or fresh install — skip
        log.debug("migration _migrate_add_max_categories: %s (skipping)", exc)


def _migrate_add_digest_times(db) -> None:
    """user_settings.morning_time / evening_time — added post-launch."""
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
    """user_digest_times table — added when custom delivery times launched."""
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
    """users.unsubscribe_token — added post-launch; back-fills existing rows."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result]
            if not cols:
                return  # table doesn't exist yet (fresh install handled by create_all)
            if "unsubscribe_token" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN unsubscribe_token TEXT"))
                # back-fill: hex(randomblob(32)) = 64 hex chars
                conn.execute(text(
                    "UPDATE users SET unsubscribe_token = hex(randomblob(32)) "
                    "WHERE unsubscribe_token IS NULL"
                ))
                conn.commit()
                log.info("migration: added users.unsubscribe_token")
    except Exception as exc:
        log.debug("migration _migrate_add_unsubscribe_token: %s (skipping)", exc)


def _migrate_create_stories_fts(db) -> None:
    """stories_fts FTS5 virtual table — SQLite only, skipped otherwise."""
    from sqlalchemy import text

    db_url = str(db.engine.url)
    if "sqlite" not in db_url:
        log.debug("migration _migrate_create_stories_fts: skipping (not SQLite)")
        return

    try:
        with db.engine.connect() as conn:
            conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS stories_fts "
                "USING fts5(id UNINDEXED, title, summary, content=stories, content_rowid=rowid)"
            ))
            conn.execute(text("INSERT INTO stories_fts(stories_fts) VALUES('rebuild')"))
            conn.commit()
            log.info("migration: created/rebuilt stories_fts FTS5 table")
    except Exception as exc:
        log.debug("migration _migrate_create_stories_fts: %s (skipping)", exc)


def _migrate_create_user_bookmarks(db) -> None:
    """user_bookmarks table — added when bookmarks launched."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_bookmarks (
                    user_id      INTEGER NOT NULL,
                    story_id     VARCHAR(64) NOT NULL,
                    bookmarked_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (user_id, story_id),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_user_bookmarks: %s (skipping)", exc)


def _migrate_create_story_clicks(db) -> None:
    """story_clicks table — added when click tracking launched."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS story_clicks (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    story_id   VARCHAR(64) NOT NULL,
                    clicked_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_story_clicks_story_id ON story_clicks(story_id)"
            ))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_story_clicks: %s (skipping)", exc)


def _migrate_create_user_blocked_keywords(db) -> None:
    """user_blocked_keywords table — added when keyword blocking launched."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_blocked_keywords (
                    user_id INTEGER NOT NULL,
                    keyword VARCHAR(128) NOT NULL,
                    PRIMARY KEY (user_id, keyword),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_user_blocked_keywords: %s (skipping)", exc)


def _migrate_create_user_custom_sources(db) -> None:
    """user_custom_sources table — added when custom RSS sources launched."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS user_custom_sources (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url     VARCHAR(512) NOT NULL,
                    name    VARCHAR(128) NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_user_custom_sources_user_id ON user_custom_sources(user_id)"
            ))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_user_custom_sources: %s (skipping)", exc)


def _migrate_create_onboarding_emails(db) -> None:
    """onboarding_emails table — added when onboarding email sequence launched."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS onboarding_emails (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    step    VARCHAR(32) NOT NULL,
                    sent_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_onboarding_emails_user_id ON onboarding_emails(user_id)"
            ))
            conn.commit()
    except Exception as exc:
        log.debug("migration _migrate_create_onboarding_emails: %s (skipping)", exc)


def _migrate_add_referral_fields(db) -> None:
    """users.referral_code + referred_by_id — added when referral system launched."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(users)"))
            cols = [row[1] for row in result]
            if not cols:
                return
            if "referral_code" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN referral_code TEXT"))
            if "referred_by_id" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN referred_by_id INTEGER REFERENCES users(id)"))
            # back-fill codes for existing users that don't have one yet
            conn.execute(text(
                "UPDATE users SET referral_code = lower(hex(randomblob(6))) WHERE referral_code IS NULL"
            ))
            conn.commit()
            log.info("migration: added referral fields to users")
    except Exception as exc:
        log.debug("_migrate_add_referral_fields: %s (skipping)", exc)


def _migrate_drop_sent_at(db) -> None:
    """Drop stories.sent_at — removed from schema. Falls back to table-rebuild on old SQLite (<3.35)."""
    from sqlalchemy import text

    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(stories)"))
            columns = [row[1] for row in result]
            if "sent_at" not in columns:
                return  # already migrated or fresh install
            # SQLite >=3.35 supports DROP COLUMN
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
        # non-SQLite or fresh install — skip
        log.debug("migration _migrate_drop_sent_at: %s (skipping)", exc)
