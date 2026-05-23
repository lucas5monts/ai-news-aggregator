"""Tests for magic-link authentication flow."""
from __future__ import annotations

import smtplib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.models import MagicLink, User, db


def _make_app():
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SECRET_KEY": "test-secret-auth",
        "WTF_CSRF_ENABLED": False,
        "SERVER_NAME": "localhost",
    })


# Patch targets — auth.py imports these at module level so patch in-module
_PATCH_SEND = "app.auth.send_digest"
_PATCH_CFG = "app.auth.load_email_config"
_FAKE_CFG = {"GMAIL_ADDRESS": "from@example.com", "GMAIL_APP_PASSWORD": "pw", "TO_ADDRESS": "from@example.com"}


class TestMagicLinkAuth(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ------------------------------------------------------------------
    # send_magic_link
    # ------------------------------------------------------------------

    def test_send_magic_link_creates_db_row(self):
        """send_magic_link should create a MagicLink row."""
        from app.auth import send_magic_link

        with patch(_PATCH_SEND), patch(_PATCH_CFG, return_value=_FAKE_CFG):
            result = send_magic_link("user@example.com")

        self.assertTrue(result)
        row = db.session.query(MagicLink).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.email, "user@example.com")

    def test_send_magic_link_email_body_contains_token_url(self):
        """The email body sent via SMTP should contain a /auth/<token> URL."""
        from app.auth import send_magic_link
        captured_html = []

        def fake_send_digest(subject, plaintext, html, **kwargs):
            captured_html.append(html)

        with patch(_PATCH_SEND, side_effect=fake_send_digest):
            with patch(_PATCH_CFG, return_value=_FAKE_CFG):
                result = send_magic_link("body@example.com")

        self.assertTrue(result)
        self.assertTrue(len(captured_html) > 0)
        self.assertIn("/auth/", captured_html[0])

    def test_send_magic_link_creates_user_if_new(self):
        """A new email should create a User row."""
        from app.auth import send_magic_link

        with patch(_PATCH_SEND), patch(_PATCH_CFG, return_value=_FAKE_CFG):
            send_magic_link("newuser@example.com")

        user = db.session.query(User).filter_by(email="newuser@example.com").first()
        self.assertIsNotNone(user)

    def test_rate_limit_blocks_after_three(self):
        """More than 3 magic links in 10 minutes should return False."""
        from app.auth import send_magic_link

        with patch(_PATCH_SEND), patch(_PATCH_CFG, return_value=_FAKE_CFG):
            for _ in range(3):
                result = send_magic_link("ratelimit@example.com")
                self.assertTrue(result)
            # 4th should be blocked
            result = send_magic_link("ratelimit@example.com")
            self.assertFalse(result)

    def test_smtp_failure_returns_none_and_does_not_block_retry(self):
        """SMTP failure returns None and the failed attempt doesn't count toward rate limit."""
        from app.auth import send_magic_link

        smtp_exc = smtplib.SMTPException("connection refused")

        # First call: SMTP raises → should return None
        with patch(_PATCH_SEND, side_effect=smtp_exc):
            with patch(_PATCH_CFG, return_value=_FAKE_CFG):
                result = send_magic_link("smtp-fail@example.com")

        self.assertIsNone(result, "SMTP failure should return None, not True/False")

        # DB row should have been cleaned up (rate-limit counter should be 0)
        count = db.session.query(MagicLink).filter_by(
            email="smtp-fail@example.com"
        ).count()
        self.assertEqual(count, 0, "failed DB row should be deleted after SMTP failure")

        # Retry should be allowed (not rate-limited)
        with patch(_PATCH_SEND), patch(_PATCH_CFG, return_value=_FAKE_CFG):
            retry_result = send_magic_link("smtp-fail@example.com")
        self.assertTrue(retry_result, "retry after SMTP failure should succeed")

    # ------------------------------------------------------------------
    # consume_token
    # ------------------------------------------------------------------

    def _insert_magic_link(self, email: str, used: bool = False) -> str:
        """Insert a fresh MagicLink and return the token."""
        from itsdangerous import URLSafeTimedSerializer
        ser = URLSafeTimedSerializer(self.app.config["SECRET_KEY"])
        token = ser.dumps({"email": email})

        now = datetime.now(timezone.utc)
        user = db.session.query(User).filter(
            db.func.lower(User.email) == email.lower()
        ).first()
        if user is None:
            user = User(email=email)
            db.session.add(user)
        ml = MagicLink(
            token=token,
            email=email,
            created_at=now,
            expires_at=now + timedelta(minutes=15),
            used_at=now if used else None,
        )
        db.session.add(ml)
        db.session.commit()
        return token

    def test_consume_valid_token_returns_user(self):
        """A fresh, valid token should return the User."""
        from app.auth import consume_token

        token = self._insert_magic_link("valid@example.com")
        user = consume_token(token)
        self.assertIsNotNone(user)
        self.assertEqual(user.email, "valid@example.com")

    def test_consume_token_marks_used_at(self):
        """After consumption, used_at should be set."""
        from app.auth import consume_token

        token = self._insert_magic_link("markused@example.com")
        consume_token(token)

        db.session.expire_all()
        row = db.session.get(MagicLink, token)
        self.assertIsNotNone(row.used_at)

    def test_consume_expired_token_returns_none(self):
        """An itsdangerous-expired token should fail."""
        from app.auth import consume_token
        from itsdangerous import SignatureExpired, URLSafeTimedSerializer

        # Patch loads to raise SignatureExpired
        old_token = "some.fake.token"
        with patch.object(
            URLSafeTimedSerializer,
            "loads",
            side_effect=SignatureExpired("expired"),
        ):
            user = consume_token(old_token)
        self.assertIsNone(user)

    def test_replay_attack_fails(self):
        """Consuming the same token twice should fail on the second attempt."""
        from app.auth import consume_token

        token = self._insert_magic_link("replay@example.com")

        user1 = consume_token(token)
        self.assertIsNotNone(user1)

        user2 = consume_token(token)
        self.assertIsNone(user2)

    def test_tampered_token_fails(self):
        """A token with a bad signature should return None."""
        from app.auth import consume_token

        result = consume_token("bad.token.sig")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Auth routes
    # ------------------------------------------------------------------

    def test_login_page_returns_200(self):
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Sign in", resp.data)

    def test_consume_bad_token_redirects_to_login(self):
        resp = self.client.get("/auth/definitely-bad-token", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
