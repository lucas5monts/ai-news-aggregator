"""SQLite persistence — tracks which stories we've already seen / sent.

Schema is intentionally tiny in Phase 1. We'll add a `digests` table
in Phase 3 (email logging) and a `clusters` table in Phase 2 (dedupe).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .pipeline import Story

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
    first_seen   TEXT NOT NULL,
    sent_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_stories_published ON stories(published_at);
CREATE INDEX IF NOT EXISTS idx_stories_sent ON stories(sent_at);
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


def mark_sent(
    conn: sqlite3.Connection,
    story_ids: list[str],
    sent_at: datetime,
) -> int:
    """Set sent_at on stories that haven't been marked sent yet. Returns row count."""
    if not story_ids:
        return 0
    placeholders = ",".join("?" * len(story_ids))
    cur = conn.execute(
        f"UPDATE stories SET sent_at=? WHERE id IN ({placeholders}) AND sent_at IS NULL",
        [sent_at.isoformat(), *story_ids],
    )
    return cur.rowcount


def upsert_stories(conn: sqlite3.Connection, stories: list[Story]) -> int:
    """Insert new stories; ignore ones we've already stored. Returns inserts."""
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
