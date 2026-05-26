"""Flask application factory for the AI News Dashboard."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

log = logging.getLogger(__name__)


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Flask application.

    Args:
        test_config: Optional dict of config overrides (used in tests).
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # --- Config -----------------------------------------------------------
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # DATABASE_URL: default SQLite; handle Heroku-style postgres:// URLs
    raw_db_url = os.environ.get("DATABASE_URL", "")
    if raw_db_url.startswith("postgres://"):
        raw_db_url = "postgresql+psycopg2://" + raw_db_url[len("postgres://"):]
    if not raw_db_url:
        raw_db_url = "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = raw_db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    flask_env = os.environ.get("FLASK_ENV", "development")
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

    # CSRF — must come after test_config is applied so WTF_CSRF_ENABLED=False
    # in test fixtures is already in app.config before CSRFProtect initialises.
    from flask_wtf.csrf import CSRFProtect
    csrf = CSRFProtect()
    # Belt-and-suspenders: explicitly honour the test-config opt-out key.
    if test_config and test_config.get("WTF_CSRF_ENABLED") is False:
        app.config["WTF_CSRF_ENABLED"] = False
    csrf.init_app(app)

    # --- Blueprints -------------------------------------------------------
    from .subscriptions import subscriptions_bp
    from .routes import main_bp
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(main_bp)

    from .template_filters import time_ago
    app.jinja_env.filters["time_ago"] = time_ago

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

