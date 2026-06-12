"""Tests for Open Graph image extraction."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.images import clear_image_cache, enrich_story_images, parse_og_image
from core.pipeline import Story
from datetime import datetime, timezone


SAMPLE_HTML = """
<html><head>
<meta property="og:image" content="https://cdn.example.com/hero.jpg">
<meta name="twitter:image" content="https://cdn.example.com/twitter.jpg">
</head><body></body></html>
"""


class TestParseOgImage(unittest.TestCase):

    def test_og_image(self):
        url = parse_og_image(SAMPLE_HTML, "https://example.com/article")
        self.assertEqual(url, "https://cdn.example.com/hero.jpg")

    def test_relative_url_resolved(self):
        html = '<meta property="og:image" content="/images/story.png">'
        url = parse_og_image(html, "https://example.com/blog/post")
        self.assertEqual(url, "https://example.com/images/story.png")

    def test_html_entities_decoded(self):
        html = (
            '<meta property="og:image" '
            'content="https://cdn.example.com/hero.png?w=1600&amp;h=900&amp;fit=fill">'
        )
        url = parse_og_image(html, "https://example.com/article")
        self.assertEqual(url, "https://cdn.example.com/hero.png?w=1600&h=900&fit=fill")

    def test_no_image(self):
        self.assertIsNone(parse_og_image("<html><head></head></html>", "https://x.com"))


class TestEnrichStoryImages(unittest.TestCase):

    def setUp(self):
        clear_image_cache()

    def tearDown(self):
        clear_image_cache()

    def test_enrich_fills_missing_images(self):
        now = datetime.now(timezone.utc)
        stories = [
            Story(
                id="a", title="T", url="https://example.com/a", summary="",
                source_name="S", source_category="industry", published_at=now,
            ),
        ]

        async def fake_fetch(client, url):
            return "https://cdn.example.com/fetched.jpg"

        with patch("core.images._fetch_og_one", side_effect=fake_fetch):
            enrich_story_images(stories)

        self.assertEqual(stories[0].image_url, "https://cdn.example.com/fetched.jpg")

    def test_enrich_skips_existing(self):
        now = datetime.now(timezone.utc)
        stories = [
            Story(
                id="a", title="T", url="https://example.com/a", summary="",
                source_name="S", source_category="industry", published_at=now,
                image_url="https://existing.com/img.jpg",
            ),
        ]

        with patch("core.images._fetch_og_one", new_callable=AsyncMock) as mock_fetch:
            enrich_story_images(stories)
            mock_fetch.assert_not_called()

        self.assertEqual(stories[0].image_url, "https://existing.com/img.jpg")


if __name__ == "__main__":
    unittest.main(verbosity=2)
