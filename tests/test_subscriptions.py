"""Tests for newsletter subscription flow."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import User, UserSettings, db


def _make_app():
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-secret-subscribe",
        "WTF_CSRF_ENABLED": False,
    })


class TestSubscribe(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_subscribe_page_returns_200(self):
        resp = self.client.get("/subscribe")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Subscribe", resp.data)

    def test_subscribe_creates_user(self):
        resp = self.client.post("/subscribe", data={
            "email": "new@example.com",
            "morning_enabled": "on",
            "timezone": "America/New_York",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/feed", resp.headers["Location"])

        user = db.session.query(User).filter_by(email="new@example.com").first()
        self.assertIsNotNone(user)
        settings = db.session.get(UserSettings, user.id)
        self.assertTrue(settings.send_email)
        self.assertTrue(settings.morning_enabled)
        self.assertFalse(settings.evening_enabled)
        self.assertEqual(settings.timezone, "America/New_York")

    def test_subscribe_existing_email_reenables(self):
        from app.subscriptions import subscribe_email
        subscribe_email("again@example.com", morning_enabled=True, evening_enabled=False)
        settings = db.session.query(UserSettings).join(User).filter(
            User.email == "again@example.com"
        ).first()
        settings.send_email = False
        db.session.commit()

        self.client.post("/subscribe", data={
            "email": "again@example.com",
            "morning_enabled": "on",
            "evening_enabled": "on",
            "timezone": "UTC",
        })
        db.session.expire_all()
        settings = db.session.query(UserSettings).join(User).filter(
            User.email == "again@example.com"
        ).first()
        self.assertTrue(settings.send_email)
        self.assertTrue(settings.evening_enabled)

    def test_subscribe_invalid_email_returns_400(self):
        resp = self.client.post("/subscribe", data={"email": "not-an-email"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
