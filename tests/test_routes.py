"""Tests for Flask routes — main and subscriptions blueprints."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import db
from core.pipeline import Story


def _empty_ai_meta():
    return {"personalized": False, "total_scored": 0, "topics_active": [], "kept": 0}


def _sample_story(**kwargs):
    defaults = dict(
        id="s1",
        title="NBA finals recap",
        url="https://example.com/s1",
        summary="Lakers win",
        source_name="ESPN",
        source_category="sports",
        published_at=datetime.now(timezone.utc),
        matched_topic="NBA",
        llm_score=0.9,
    )
    defaults.update(kwargs)
    return Story(**defaults)


def _make_app():
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-routes-secret",
        "WTF_CSRF_ENABLED": False,
    })


class TestRoutesPublic(unittest.TestCase):
    """All main routes are public — no login required."""

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_root_redirects_to_feed(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/feed", resp.headers["Location"])

    def test_feed_returns_200(self):
        with patch("app.routes._run_pipeline_global", return_value=([], 0, _empty_ai_meta())):
            resp = self.client.get("/feed")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<html", resp.data.lower())

    def test_feed_shows_nudge_without_personalization(self):
        with patch("app.routes._run_pipeline_global", return_value=([], 0, _empty_ai_meta())):
            resp = self.client.get("/feed")
        self.assertIn(b"This is the general feed", resp.data)

    def test_feed_shows_personalized_banner(self):
        story = _sample_story()
        ai_meta = {
            "personalized": True,
            "total_scored": 100,
            "topics_active": ["NBA"],
            "kept": 1,
        }
        with patch("app.routes._run_pipeline_global", return_value=([story], 100, ai_meta)):
            resp = self.client.get("/feed")
        self.assertIn(b"Personalized by AI", resp.data)
        self.assertIn(b"NBA", resp.data)

    def test_preview_returns_200(self):
        mock_html = "<html><body>Preview content</body></html>"
        with patch("app.routes._run_pipeline_filtered", return_value=([], 0)):
            with patch("core.render.render_html", return_value=mock_html):
                resp = self.client.get("/preview")
        self.assertEqual(resp.status_code, 200)

    def test_subscribe_returns_200(self):
        resp = self.client.get("/subscribe")
        self.assertEqual(resp.status_code, 200)


class TestSubscriberCookie(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_subscribe_sets_subscriber_cookie(self):
        resp = self.client.post("/subscribe", data={
            "email": "cookie@example.com",
            "password": "securepass",
            "confirm_password": "securepass",
            "morning_enabled": "on",
            "timezone": "UTC",
            "topics": "NBA, tech",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("subscriber_id=", resp.headers.get("Set-Cookie", ""))

    def test_unsubscribe_clears_subscriber_cookie(self):
        from app.subscriptions import subscribe_email
        user = subscribe_email("clear@example.com", morning_enabled=True)
        token = user.unsubscribe_token
        from app.subscriber_cookie import set_subscriber_cookie
        from flask import make_response
        with self.app.test_request_context():
            resp = make_response("")
            set_subscriber_cookie(resp, user.id)
            cookie_val = resp.headers.get("Set-Cookie", "")
        import re
        m = re.search(r"subscriber_id=([^;]+)", cookie_val)
        self.assertIsNotNone(m)
        self.client.set_cookie("subscriber_id", m.group(1))
        resp = self.client.post(f"/unsubscribe/{token}")
        self.assertEqual(resp.status_code, 200)
        cleared = resp.headers.get("Set-Cookie", "")
        self.assertIn("subscriber_id=", cleared)
        self.assertTrue(
            "Max-Age=0" in cleared or 'subscriber_id=""' in cleared or "expires=" in cleared.lower()
        )


class TestCSRFProtection(unittest.TestCase):
    """CSRF middleware should block POST requests that carry no token."""

    def test_csrf_blocks_subscribe_without_token(self):
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-csrf-secret",
        })
        with app.app_context():
            client = app.test_client()
            resp = client.post("/subscribe", data={"email": "csrf@example.com"})
            self.assertIn(
                resp.status_code, (400, 403),
                f"expected 400/403 for missing CSRF token, got {resp.status_code}",
            )
            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main(verbosity=2)
