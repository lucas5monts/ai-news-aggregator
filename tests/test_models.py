"""Tests for SQLAlchemy models: creation, seeding, round-trip."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import Digest, DigestStory, MagicLink, User, UserSettings, UserSource, db


def _make_app():
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-secret",
        "WTF_CSRF_ENABLED": False,
    })


class TestModels(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_tables_create_cleanly(self):
        """All expected tables should exist after create_all."""
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = set(inspector.get_table_names())
        for expected in ("users", "magic_links", "user_settings", "user_sources",
                         "digests", "digest_stories"):
            self.assertIn(expected, tables, f"missing table: {expected}")

    def test_user_create_and_retrieve(self):
        from datetime import datetime, timezone
        u = User(email="alice@example.com", created_at=datetime.now(timezone.utc))
        db.session.add(u)
        db.session.commit()

        fetched = db.session.query(User).filter_by(email="alice@example.com").first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.email, "alice@example.com")
        self.assertIsNotNone(fetched.id)

    def test_user_settings_round_trip(self):
        u = User(email="bob@example.com")
        db.session.add(u)
        db.session.flush()

        settings = UserSettings(
            user_id=u.id,
            send_email=False,
            morning_enabled=True,
            evening_enabled=False,
            max_stories=10,
            timezone="America/New_York",
        )
        db.session.add(settings)
        db.session.commit()

        loaded = db.session.get(UserSettings, u.id)
        self.assertFalse(loaded.send_email)
        self.assertTrue(loaded.morning_enabled)
        self.assertFalse(loaded.evening_enabled)
        self.assertEqual(loaded.max_stories, 10)
        self.assertEqual(loaded.timezone, "America/New_York")

    def test_user_source_round_trip(self):
        u = User(email="carol@example.com")
        db.session.add(u)
        db.session.flush()

        us = UserSource(user_id=u.id, source_name="OpenAI News", enabled=True)
        us2 = UserSource(user_id=u.id, source_name="Wired AI", enabled=False)
        db.session.add_all([us, us2])
        db.session.commit()

        rows = db.session.query(UserSource).filter_by(user_id=u.id).all()
        self.assertEqual(len(rows), 2)
        by_name = {r.source_name: r.enabled for r in rows}
        self.assertTrue(by_name["OpenAI News"])
        self.assertFalse(by_name["Wired AI"])

    def test_digest_and_stories(self):
        from datetime import datetime, timezone
        u = User(email="dave@example.com")
        db.session.add(u)
        db.session.flush()

        d = Digest(
            user_id=u.id,
            edition="morning",
            sent_at=datetime.now(timezone.utc),
            story_count=3,
            subject="Morning Brief",
            html_blob="<html></html>",
        )
        db.session.add(d)
        db.session.flush()

        for sid in ("abc123", "def456", "ghi789"):
            db.session.add(DigestStory(digest_id=d.id, story_id=sid))
        db.session.commit()

        loaded = db.session.get(Digest, d.id)
        self.assertEqual(loaded.edition, "morning")
        self.assertEqual(loaded.story_count, 3)
        self.assertEqual(len(loaded.stories), 3)

    def test_dev_user_seeding_via_auth(self):
        """_seed_user_defaults creates UserSettings + UserSource rows."""
        from app.auth import _seed_user_defaults

        u = User(email="seed@example.com")
        db.session.add(u)
        db.session.flush()
        _seed_user_defaults(u)
        db.session.commit()

        settings = db.session.get(UserSettings, u.id)
        self.assertIsNotNone(settings)
        self.assertTrue(settings.morning_enabled)

        sources = db.session.query(UserSource).filter_by(user_id=u.id).all()
        self.assertGreater(len(sources), 0)

    def test_magic_link_model(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        ml = MagicLink(
            token="abc.token.xyz",
            email="test@example.com",
            created_at=now,
            expires_at=now + timedelta(minutes=15),
        )
        db.session.add(ml)
        db.session.commit()

        fetched = db.session.get(MagicLink, "abc.token.xyz")
        self.assertIsNotNone(fetched)
        self.assertIsNone(fetched.used_at)
        self.assertEqual(fetched.email, "test@example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
