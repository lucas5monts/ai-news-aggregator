"""Tests for email/password authentication."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import User, db


def _make_app():
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-secret-auth",
        "WTF_CSRF_ENABLED": False,
    })


class TestAuth(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _create_user(self, email: str = "user@example.com", password: str = "password123") -> User:
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def test_login_page_returns_200(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Log in", resp.data)

    def test_login_success_redirects_to_preferences(self):
        self._create_user()
        resp = self.client.post("/login", data={
            "email": "user@example.com",
            "password": "password123",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/preferences", resp.headers["Location"])

    def test_login_invalid_password_returns_401(self):
        self._create_user()
        resp = self.client.post("/login", data={
            "email": "user@example.com",
            "password": "wrongpassword",
        })
        self.assertEqual(resp.status_code, 401)

    def test_login_unknown_email_returns_401(self):
        resp = self.client.post("/login", data={
            "email": "nobody@example.com",
            "password": "password123",
        })
        self.assertEqual(resp.status_code, 401)

    def test_preferences_requires_login(self):
        resp = self.client.get("/preferences", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_logout_clears_session(self):
        self._create_user()
        self.client.post("/login", data={
            "email": "user@example.com",
            "password": "password123",
        })
        resp = self.client.post("/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get("/preferences", follow_redirects=False)
        self.assertIn("/login", resp.headers["Location"])

    def test_logout_rejects_get(self):
        self._create_user()
        self.client.post("/login", data={
            "email": "user@example.com",
            "password": "password123",
        })
        resp = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(resp.status_code, 405)


if __name__ == "__main__":
    unittest.main(verbosity=2)
