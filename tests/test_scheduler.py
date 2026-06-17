"""Tests for the APScheduler digest logic."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scheduler import is_users_morning, is_users_evening, _is_hour_minute


class TestTimezonePredicates(unittest.TestCase):
    """Test the 'is it the user's morning/evening right now?' predicates."""

    def _utc(self, hour: int, minute: int = 0) -> datetime:
        """Helper: make a timezone-aware UTC datetime with a specific time."""
        return datetime(2025, 5, 23, hour, minute, 0, tzinfo=timezone.utc)

    def test_morning_los_angeles_summer(self):
        """6 AM PDT = 13:00 UTC in summer (UTC-7)."""
        utc_time = self._utc(13, 0)
        self.assertTrue(is_users_morning("America/Los_Angeles", now_utc=utc_time))

    def test_not_morning_los_angeles(self):
        """7 AM PDT = 14:00 UTC — not 6 AM."""
        utc_time = self._utc(14, 0)
        self.assertFalse(is_users_morning("America/Los_Angeles", now_utc=utc_time))

    def test_morning_new_york_summer(self):
        """6 AM EDT = 10:00 UTC in summer (UTC-4)."""
        utc_time = self._utc(10, 0)
        self.assertTrue(is_users_morning("America/New_York", now_utc=utc_time))

    def test_morning_london_summer(self):
        """6 AM BST = 05:00 UTC in summer (UTC+1)."""
        utc_time = self._utc(5, 0)
        self.assertTrue(is_users_morning("Europe/London", now_utc=utc_time))

    def test_morning_tokyo(self):
        """6 AM JST = 21:00 UTC previous day (UTC+9). Test with same-day UTC."""
        utc_time = self._utc(21, 0)
        self.assertTrue(is_users_morning("Asia/Tokyo", now_utc=utc_time))

    def test_evening_los_angeles_summer(self):
        """8 PM PDT = 03:00 UTC next day — test with 03:00 UTC."""
        utc_time = self._utc(3, 0)
        self.assertTrue(is_users_evening("America/Los_Angeles", now_utc=utc_time))

    def test_not_evening_los_angeles(self):
        """9 PM PDT = 04:00 UTC — not 8 PM."""
        utc_time = self._utc(4, 0)
        self.assertFalse(is_users_evening("America/Los_Angeles", now_utc=utc_time))

    def test_minute_matters(self):
        """6:01 AM should NOT match (we want exactly 6:00)."""
        # LA summer: 6:01 AM PDT = 13:01 UTC
        utc_time = self._utc(13, 1)
        self.assertFalse(is_users_morning("America/Los_Angeles", now_utc=utc_time))

    def test_utc_timezone(self):
        """UTC user: 6:00 UTC == morning."""
        utc_time = self._utc(6, 0)
        self.assertTrue(is_users_morning("UTC", now_utc=utc_time))

    def test_unknown_timezone_falls_back_to_utc(self):
        """Unknown timezone should fall back to UTC without crashing."""
        utc_time = self._utc(6, 0)
        # Should not raise
        result = is_users_morning("Not/ATimezone", now_utc=utc_time)
        self.assertTrue(result)  # 6:00 UTC == 6:00 in fallback UTC

    def test_custom_morning_time_matches(self):
        """Custom morning time 07:30 should match at the right UTC instant."""
        # 7:30 AM UTC user
        utc_time = self._utc(7, 30)
        self.assertTrue(is_users_morning("UTC", time_str="07:30", now_utc=utc_time))
        # Default 06:00 should NOT match at 07:30
        self.assertFalse(is_users_morning("UTC", now_utc=utc_time))

    def test_custom_evening_time_matches(self):
        """Custom evening time 21:15 should match at the right UTC instant."""
        utc_time = self._utc(21, 15)
        self.assertTrue(is_users_evening("UTC", time_str="21:15", now_utc=utc_time))
        # Default 20:00 should NOT match at 21:15
        self.assertFalse(is_users_evening("UTC", now_utc=utc_time))

    def test_custom_time_respects_timezone(self):
        """Custom time is interpreted in the user's local timezone."""
        # 9:00 AM EDT (summer, UTC-4) == 13:00 UTC
        utc_time = self._utc(13, 0)
        self.assertTrue(
            is_users_morning("America/New_York", time_str="09:00", now_utc=utc_time)
        )

    def test_malformed_time_str_falls_back_to_six(self):
        """A malformed time string falls back to 06:00."""
        from app.scheduler import _parse_time_str
        self.assertEqual(_parse_time_str("not-a-time"), (6, 0))
        self.assertEqual(_parse_time_str(""), (6, 0))
        # And the predicate uses that fallback: 06:00 UTC matches
        utc_time = self._utc(6, 0)
        self.assertTrue(is_users_morning("UTC", time_str="garbage", now_utc=utc_time))


class TestDigestJobIdempotency(unittest.TestCase):
    """Test that _already_sent_today prevents double-sends."""

    def setUp(self):
        from app import create_app
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-sched",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.models import db
        db.create_all()
        self.db = db

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    def test_no_digest_yet_returns_false(self):
        from app.scheduler import _already_sent_today
        now = datetime.now(timezone.utc)
        self.assertFalse(_already_sent_today(999, "morning", now))

    def test_already_sent_returns_true(self):
        from app.scheduler import _already_sent_today
        from app.models import Digest, User

        user = User(email="sent@example.com")
        self.db.session.add(user)
        self.db.session.flush()

        now = datetime.now(timezone.utc)
        d = Digest(
            user_id=user.id,
            edition="morning",
            sent_at=now,
            story_count=5,
            subject="Morning Brief",
            html_blob="",
        )
        self.db.session.add(d)
        self.db.session.commit()

        self.assertTrue(_already_sent_today(user.id, "morning", now))

    def test_yesterday_digest_does_not_block_today(self):
        from app.scheduler import _already_sent_today
        from app.models import Digest, User

        user = User(email="yesterday@example.com")
        self.db.session.add(user)
        self.db.session.flush()

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        d = Digest(
            user_id=user.id,
            edition="morning",
            sent_at=yesterday,
            story_count=3,
            subject="Yesterday",
            html_blob="",
        )
        self.db.session.add(d)
        self.db.session.commit()

        now = datetime.now(timezone.utc)
        self.assertFalse(_already_sent_today(user.id, "morning", now))

    def test_send_email_false_skips_user(self):
        """Users with send_email=False should be skipped in the digest job."""
        from app.models import User, UserSettings
        from app.scheduler import _digest_job

        user = User(email="nosend@example.com")
        self.db.session.add(user)
        self.db.session.flush()

        settings = UserSettings(
            user_id=user.id,
            send_email=False,  # disabled
            morning_enabled=True,
        )
        self.db.session.add(settings)
        self.db.session.commit()

        # _send_digest_for_user should NOT be called
        with patch("app.scheduler._send_digest_for_user") as mock_send:
            with patch("app.scheduler.is_users_morning", return_value=True):
                _digest_job("morning", self.app)
        mock_send.assert_not_called()

    def test_morning_disabled_skips_user(self):
        """Users with morning_enabled=False should be skipped."""
        from app.models import User, UserSettings
        from app.scheduler import _digest_job

        user = User(email="nomorning@example.com")
        self.db.session.add(user)
        self.db.session.flush()

        settings = UserSettings(
            user_id=user.id,
            send_email=True,
            morning_enabled=False,  # disabled
        )
        self.db.session.add(settings)
        self.db.session.commit()

        with patch("app.scheduler._send_digest_for_user") as mock_send:
            with patch("app.scheduler.is_users_morning", return_value=True):
                _digest_job("morning", self.app)
        mock_send.assert_not_called()


class TestCustomDigestJob(unittest.TestCase):
    """Test the user-defined custom-times digest job."""

    def setUp(self):
        from app import create_app
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-custom",
        })
        self.ctx = self.app.app_context()
        self.ctx.push()
        from app.models import db
        db.create_all()
        self.db = db

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    def _make_user(self, **settings_kwargs):
        from app.models import User, UserSettings
        user = User(email=f"u{settings_kwargs.get('user_id', 'x')}@example.com")
        self.db.session.add(user)
        self.db.session.flush()
        settings = UserSettings(user_id=user.id, **settings_kwargs)
        self.db.session.add(settings)
        return user, settings

    def test_custom_time_triggers_send(self):
        from app.models import UserDigestTime
        from app.scheduler import _custom_digest_job

        user, _ = self._make_user(send_email=True, timezone="UTC")
        self.db.session.add(UserDigestTime(user_id=user.id, send_time="12:30", enabled=True))
        self.db.session.commit()

        now = datetime(2025, 5, 23, 12, 30, 0, tzinfo=timezone.utc)
        with patch("app.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            with patch("app.scheduler._send_digest_for_user") as mock_send:
                _custom_digest_job(self.app)

        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["log_edition"], "custom@12:30")
        self.assertEqual(kwargs["render_edition"], "evening")  # hour 12 is not < 12
        self.assertEqual(kwargs["send_time"], "12:30")

    def test_custom_time_not_matching_skips(self):
        from app.models import UserDigestTime
        from app.scheduler import _custom_digest_job

        user, _ = self._make_user(send_email=True, timezone="UTC")
        self.db.session.add(UserDigestTime(user_id=user.id, send_time="12:30", enabled=True))
        self.db.session.commit()

        now = datetime(2025, 5, 23, 9, 0, 0, tzinfo=timezone.utc)
        with patch("app.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            with patch("app.scheduler._send_digest_for_user") as mock_send:
                _custom_digest_job(self.app)
        mock_send.assert_not_called()

    def test_custom_time_duplicate_of_preset_is_skipped(self):
        """A custom time equal to an enabled preset must not double-send."""
        from app.models import UserDigestTime
        from app.scheduler import _custom_digest_job

        user, _ = self._make_user(
            send_email=True, timezone="UTC", morning_enabled=True, morning_time="06:00"
        )
        self.db.session.add(UserDigestTime(user_id=user.id, send_time="06:00", enabled=True))
        self.db.session.commit()

        now = datetime(2025, 5, 23, 6, 0, 0, tzinfo=timezone.utc)
        with patch("app.scheduler.datetime") as mock_dt:
            mock_dt.now.return_value = now
            with patch("app.scheduler._send_digest_for_user") as mock_send:
                _custom_digest_job(self.app)
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
