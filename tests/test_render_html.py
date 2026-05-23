"""Tests for HTML rendering and Gmail delivery (no network / no real SMTP)."""
from __future__ import annotations

import html as _html
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import pipeline, render
from core.deliver import send_digest

# Reuse the synthetic feed builder from the pipeline test
from tests.test_pipeline_with_sample import build_raw_entries, SAMPLE_FEEDS


def _build_stories() -> list:
    raw = build_raw_entries()
    stories = pipeline.normalize(raw, max_summary_chars=280)
    keywords = ["ai", "openai", "anthropic", "model", "moe", "transformer",
                "diffusers", "fine-tun"]
    stories = pipeline.filter_relevant(stories, keywords, window_hours=24)
    source_weights = {name: w for (name, _, w), _ in SAMPLE_FEEDS.items()}
    stories = pipeline.rank(stories, source_weights)
    stories = pipeline.dedupe(stories)
    stories = pipeline.cap(stories, 15)
    return stories


class TestRenderHtml(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        stories = _build_stories()
        cls.stories = stories
        cls.html = render.render_html(
            stories,
            edition="morning",
            category_order=["industry", "research", "tools", "policy"],
            total_scanned=20,
        )

    def test_is_html_document(self):
        self.assertIn("<html", self.html)
        self.assertIn("</html>", self.html)

    def test_all_titles_present(self):
        # Unescape HTML entities for plain-text comparison (Jinja2 uses &#39;
        # while Python's html.escape uses &#x27; — same char, different encoding)
        decoded = _html.unescape(self.html)
        for s in self.stories:
            self.assertIn(s.title, decoded, f"title missing: {s.title!r}")

    def test_urls_as_hrefs(self):
        for s in self.stories:
            self.assertIn(f'href="{s.url}"', self.html, f"href missing for {s.url!r}")

    def test_also_covered_by_wired(self):
        self.assertIn("Also covered by: Wired AI", self.html)

    def test_no_forbidden_tags(self):
        lower = self.html.lower()
        for tag in ("<script", "<iframe", "<style"):
            self.assertNotIn(tag, lower, f"forbidden tag found: {tag!r}")

    def test_no_external_resources(self):
        lower = self.html.lower()
        for marker in ("fonts.google", "fonts.gstatic", "tracking", "pixel"):
            self.assertNotIn(marker, lower)


class TestSendDigest(unittest.TestCase):

    def test_smtp_called_correctly(self):
        with patch("smtplib.SMTP_SSL") as MockSSL:
            smtp = MockSSL.return_value.__enter__.return_value

            send_digest(
                subject="AI Brief · Thu May 21 · 6:00 AM · 5 stories",
                plaintext="hello plain",
                html="<html><body>hello html</body></html>",
                to_address="to@example.com",
                from_address="from@example.com",
                app_password="test-secret",
            )

            smtp.login.assert_called_once_with("from@example.com", "test-secret")
            smtp.sendmail.assert_called_once()

            from_arg, to_arg, payload_bytes = smtp.sendmail.call_args[0]
            self.assertEqual(from_arg, "from@example.com")
            self.assertEqual(to_arg, "to@example.com")

            payload = payload_bytes.decode("utf-8", errors="replace")
            self.assertIn("text/plain", payload)
            self.assertIn("text/html", payload)

    def test_password_not_in_logs(self):
        """The app password must never appear in log output."""
        import logging
        import io

        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        log = logging.getLogger("core.deliver")
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)

        try:
            with patch("smtplib.SMTP_SSL"):
                send_digest(
                    subject="test",
                    plaintext="p",
                    html="<html></html>",
                    to_address="to@example.com",
                    from_address="from@example.com",
                    app_password="supersecretpassword",
                )
        finally:
            log.removeHandler(handler)

        self.assertNotIn("supersecretpassword", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
