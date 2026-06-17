"""SQLAlchemy models for the AI News Dashboard.

Tables:
    users           — newsletter subscribers
    user_settings   — per-user digest preferences
    user_sources    — per-user RSS source toggles (used by scheduler)
    digests         — log of every sent digest (with rendered HTML blob)
    digest_stories  — join table: which stories were in each digest

The global `stories` table is managed by core.storage (SQLite/raw SQL).
We leave it untouched here — it is the shared story cache.
"""
from __future__ import annotations

import secrets as _secrets
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __allow_unmapped__ = True

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now_utc, nullable=False)
    unsubscribe_token = db.Column(
        db.String(64),
        unique=True,
        nullable=False,
        default=lambda: _secrets.token_urlsafe(32),
    )

    # relationships
    settings = db.relationship(
        "UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sources = db.relationship(
        "UserSource", back_populates="user", cascade="all, delete-orphan"
    )
    topics = db.relationship(
        "UserTopic", back_populates="user", cascade="all, delete-orphan"
    )
    digest_times = db.relationship(
        "UserDigestTime", back_populates="user", cascade="all, delete-orphan"
    )
    digests = db.relationship(
        "Digest", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class UserSettings(db.Model):
    __tablename__ = "user_settings"
    __allow_unmapped__ = True

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    send_email = db.Column(db.Boolean, default=True, nullable=False)
    morning_enabled = db.Column(db.Boolean, default=True, nullable=False)
    evening_enabled = db.Column(db.Boolean, default=True, nullable=False)
    max_stories = db.Column(db.Integer, default=15, nullable=False)
    max_categories = db.Column(db.Integer, nullable=True)  # None = show all categories
    timezone = db.Column(db.String(64), default="America/Los_Angeles", nullable=False)
    morning_time = db.Column(db.String(5), default="06:00", nullable=False)  # "HH:MM"
    evening_time = db.Column(db.String(5), default="20:00", nullable=False)  # "HH:MM"

    user = db.relationship("User", back_populates="settings")

    def __repr__(self) -> str:
        return f"<UserSettings user_id={self.user_id}>"


class UserSource(db.Model):
    __tablename__ = "user_sources"
    __allow_unmapped__ = True

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    source_name = db.Column(db.String(128), primary_key=True)
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship("User", back_populates="sources")

    def __repr__(self) -> str:
        return f"<UserSource user_id={self.user_id} source={self.source_name!r} enabled={self.enabled}>"


class UserTopic(db.Model):
    __tablename__ = "user_topics"
    __allow_unmapped__ = True

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    topic = db.Column(db.String(128), primary_key=True)  # e.g. "F1 racing"
    created_at = db.Column(db.DateTime(timezone=True), default=_now_utc, nullable=False)

    user = db.relationship("User", back_populates="topics")

    def __repr__(self) -> str:
        return f"<UserTopic user_id={self.user_id} topic={self.topic!r}>"


class UserDigestTime(db.Model):
    """Extra, user-defined delivery times beyond the morning/evening presets.

    Each row is one custom "HH:MM" send time. The scheduler treats these as
    additional editions, keyed by time so several can fire on the same day.
    """

    __tablename__ = "user_digest_times"
    __allow_unmapped__ = True

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    send_time = db.Column(db.String(5), primary_key=True)  # "HH:MM" (24-hour)
    enabled = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship("User", back_populates="digest_times")

    def __repr__(self) -> str:
        return f"<UserDigestTime user_id={self.user_id} send_time={self.send_time!r}>"


class Digest(db.Model):
    __tablename__ = "digests"
    __allow_unmapped__ = True

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    edition = db.Column(db.String(16), nullable=False)  # morning / evening / test
    sent_at = db.Column(db.DateTime(timezone=True), default=_now_utc, nullable=False)
    story_count = db.Column(db.Integer, nullable=False, default=0)
    subject = db.Column(db.String(256), nullable=False, default="")
    html_blob = db.Column(db.Text, nullable=False, default="")

    user = db.relationship("User", back_populates="digests")
    stories = db.relationship(
        "DigestStory", back_populates="digest", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Digest id={self.id} user_id={self.user_id} edition={self.edition!r}>"


class DigestStory(db.Model):
    __tablename__ = "digest_stories"
    __allow_unmapped__ = True

    digest_id = db.Column(db.Integer, db.ForeignKey("digests.id"), primary_key=True)
    story_id = db.Column(db.String(32), primary_key=True)

    digest = db.relationship("Digest", back_populates="stories")

    def __repr__(self) -> str:
        return f"<DigestStory digest_id={self.digest_id} story_id={self.story_id!r}>"
