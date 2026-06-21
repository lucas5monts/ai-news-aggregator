"""SQLite story cache — used by the CLI and the hourly scheduler job."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .pipeline import Story

# sent_at is intentionally omitted — the Flask app dropped that column.
# Keep the schema in sync with _migrate_drop_sent_at in app/__init__.py.
SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    summary      TEXT NOT NULL,
    source_name  TEXT NOT NULL,
    category     TEXT NOT NULL,
    published_at TEXT NOT NULL,
    score        REAL NOT NULL,
    first_seen   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stories_published ON stories(published_at);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_stories(conn: sqlite3.Connection, stories: list[Story]) -> int:
    """Insert new stories; skip ones already stored. Returns count of new inserts."""
    now = datetime.utcnow().isoformat()
    inserted = 0
    for s in stories:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO stories
                (id, title, url, summary, source_name, category,
                 published_at, score, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                s.id,
                s.title,
                s.url,
                s.summary,
                s.source_name,
                s.source_category,
                s.published_at.isoformat(),
                s.score,
                now,
            ),
        )
        inserted += cur.rowcount
    return inserted
