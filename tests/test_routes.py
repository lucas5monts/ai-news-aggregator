"""Tests for Flask routes — main and subscriptions blueprints."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import db


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
        with patch("app.routes._run_pipeline_global", return_value=([], 0)):
            resp = self.client.get("/feed")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<html", resp.data.lower())

    def test_preview_returns_200(self):
        mock_html = "<html><body>Preview content</body></html>"
        with patch("app.routes._run_pipeline_global", return_value=([], 0)):
            with patch("core.render.render_html", return_value=mock_html):
                resp = self.client.get("/preview")
        self.assertEqual(resp.status_code, 200)

    def test_subscribe_returns_200(self):
        resp = self.client.get("/subscribe")
        self.assertEqual(resp.status_code, 200)


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
