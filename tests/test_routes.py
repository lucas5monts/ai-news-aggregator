"""Tests for Flask routes — auth and main blueprints."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import User, UserSettings, UserSource, db


def _make_app():
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-routes-secret",
        "WTF_CSRF_ENABLED": False,
    })


def _create_user(email: str = "test@example.com") -> User:
    """Create a user with default settings and sources."""
    from app.auth import _seed_user_defaults
    u = User(email=email)
    db.session.add(u)
    db.session.flush()
    _seed_user_defaults(u)
    db.session.commit()
    return u


def _login(client, app, user: User):
    """Log the user in via Flask-Login's test request context."""
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


class TestRoutesUnauthenticated(unittest.TestCase):
    """Routes should redirect to /login when not authenticated."""

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

    def test_feed_redirects_to_login(self):
        resp = self.client.get("/feed", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_settings_redirects_to_login(self):
        resp = self.client.get("/settings", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_preview_redirects_to_login(self):
        resp = self.client.get("/preview", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_archive_redirects_to_login(self):
        resp = self.client.get("/archive", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])


class TestRoutesAuthenticated(unittest.TestCase):
    """Authenticated routes should return 200 and expected content."""

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        self.user = _create_user("auth@example.com")
        _login(self.client, self.app, self.user)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_root_redirects_to_feed(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/feed", resp.headers["Location"])

    def test_feed_returns_200(self):
        # Mock the pipeline to avoid live network calls
        empty_stories = []
        with patch("app.routes._run_pipeline_for_user", return_value=(empty_stories, 0)):
            resp = self.client.get("/feed")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<html", resp.data.lower())

    def test_settings_get_returns_200(self):
        resp = self.client.get("/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Settings", resp.data)

    def test_settings_post_persists_changes(self):
        """POST /settings should update UserSettings in DB."""
        form_data = {
            "send_email": "on",
            "morning_enabled": "on",
            # evening_enabled omitted → False
            "max_stories": "8",
            "timezone": "America/New_York",
        }
        resp = self.client.post("/settings", data=form_data)
        self.assertIn(resp.status_code, (200, 302))

        settings = db.session.get(UserSettings, self.user.id)
        self.assertIsNotNone(settings)
        self.assertTrue(settings.send_email)
        self.assertTrue(settings.morning_enabled)
        self.assertFalse(settings.evening_enabled)
        self.assertEqual(settings.max_stories, 8)
        self.assertEqual(settings.timezone, "America/New_York")

    def test_preview_returns_200(self):
        mock_html = "<html><body>Preview content</body></html>"
        with patch("app.routes._run_pipeline_for_user", return_value=([], 0)):
            with patch("core.render.render_html", return_value=mock_html):
                resp = self.client.get("/preview")
        self.assertEqual(resp.status_code, 200)

    def test_archive_returns_200(self):
        resp = self.client.get("/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Archive", resp.data)

    def test_archive_view_nonexistent_redirects(self):
        resp = self.client.get("/archive/99999", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/archive", resp.headers["Location"])


class TestRoutesSettingsSources(unittest.TestCase):
    """Test that per-source settings are saved correctly."""

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()
        self.user = _create_user("sources@example.com")
        _login(self.client, self.app, self.user)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_source_toggle_saved(self):
        """Posting settings with specific sources checked saves correctly."""
        form_data = {
            "send_email": "on",
            "morning_enabled": "on",
            "max_stories": "15",
            "timezone": "UTC",
            "source_OpenAI News": "on",
            # "source_Wired AI" absent → disabled
        }
        self.client.post("/settings", data=form_data)

        openai_src = db.session.get(UserSource, (self.user.id, "OpenAI News"))
        wired_src = db.session.get(UserSource, (self.user.id, "Wired AI"))
        if openai_src:
            self.assertTrue(openai_src.enabled)
        if wired_src:
            self.assertFalse(wired_src.enabled)


class TestCSRFProtection(unittest.TestCase):
    """CSRF middleware should block POST requests that carry no token."""

    def test_csrf_blocks_post_without_token(self):
        """POST to /settings without a csrf_token field should return 400."""
        # Create the app WITH CSRF enabled (no WTF_CSRF_ENABLED=False override).
        app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-csrf-secret",
            # WTF_CSRF_ENABLED omitted → defaults to True
        })
        with app.app_context():
            # Create and log in a user
            from app.auth import _seed_user_defaults
            user = User(email="csrf@example.com")
            db.session.add(user)
            db.session.flush()
            _seed_user_defaults(user)
            db.session.commit()

            client = app.test_client()
            with client.session_transaction() as sess:
                sess["_user_id"] = str(user.id)
                sess["_fresh"] = True

            # POST without csrf_token — Flask-WTF returns 400
            resp = client.post("/settings", data={
                "send_email": "on",
                "max_stories": "15",
                "timezone": "UTC",
            })
            self.assertIn(
                resp.status_code, (400, 403),
                f"expected 400/403 for missing CSRF token, got {resp.status_code}",
            )

            db.session.remove()
            db.drop_all()


if __name__ == "__main__":
    unittest.main(verbosity=2)
