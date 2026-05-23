"""SQLAlchemy models for the AI News Dashboard.

Tables:
    users           — registered users (multi-user capable)
    magic_links     — one-time login tokens (15-minute TTL)
    user_settings   — per-user digest preferences
    user_sources    — per-user RSS source toggles
    digests         — log of every sent digest (with rendered HTML blob)
    digest_stories  — join table: which stories were in each digest

The global `stories` table is managed by core.storage (SQLite/raw SQL).
We leave it untouched here — it is the shared story cache.
"""
from __future__ import annotations

from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    __allow_unmapped__ = True

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(256), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_now_utc, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # relationships
    settings = db.relationship(
        "UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sources = db.relationship(
        "UserSource", back_populates="user", cascade="all, delete-orphan"
    )
    digests = db.relationship(
        "Digest", back_populates="user", cascade="all, delete-orphan"
    )

    def get_id(self) -> str:  # Flask-Login requires str
        return str(self.id)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


class MagicLink(db.Model):
    __tablename__ = "magic_links"
    __allow_unmapped__ = True

    token = db.Column(db.String(512), primary_key=True)
    email = db.Column(db.String(256), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_now_utc, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<MagicLink email={self.email!r} used={self.used_at is not None}>"


class UserSettings(db.Model):
    __tablename__ = "user_settings"
    __allow_unmapped__ = True

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    send_email = db.Column(db.Boolean, default=True, nullable=False)
    morning_enabled = db.Column(db.Boolean, default=True, nullable=False)
    evening_enabled = db.Column(db.Boolean, default=True, nullable=False)
    max_stories = db.Column(db.Integer, default=15, nullable=False)
    timezone = db.Column(db.String(64), default="America/Los_Angeles", nullable=False)

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
