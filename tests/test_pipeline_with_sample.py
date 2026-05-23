"""End-to-end pipeline test using a synthetic RSS feed.

This exists because the dev sandbox can't reach live RSS hosts.
On a real machine, you just run `python -m src.main morning` and get
real feeds — this test confirms the normalize→filter→rank→render code
works without needing network.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

# Make `src` importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import feedparser  # noqa: E402

from src import pipeline, render, storage  # noqa: E402
from src.fetch import RawEntry  # noqa: E402

# -------- synthesize realistic RSS feeds --------

NOW = datetime.now(timezone.utc)


def _make_entry(title: str, link: str, summary: str, hours_ago: float) -> dict:
    pub = NOW - timedelta(hours=hours_ago)
    return {
        "title": title,
        "link": link,
        "summary": summary,
        "published": format_datetime(pub),
        "id": link,
    }


SAMPLE_FEEDS = {
    ("OpenAI News", "industry", 1.5): [
        _make_entry(
            "OpenAI launches new enterprise tier with custom fine-tuning",
            "https://openai.com/news/enterprise-tier",
            "OpenAI today announced an enterprise tier offering customizable GPT "
            "models with private fine-tuning, expanded context, and dedicated "
            "capacity for large organizations.",
            hours_ago=2,
        ),
        _make_entry(
            "Sora 2 API now generally available",
            "https://openai.com/news/sora-2-api",
            "The Sora 2 video generation model is now available via API for all "
            "developers. The release includes new safety guardrails and a "
            "30-second clip length cap.",
            hours_ago=8,
        ),
    ],
    ("Hugging Face Blog", "tools", 1.2): [
        _make_entry(
            "Introducing Diffusers 1.0: stable, fast, production-ready",
            "https://huggingface.co/blog/diffusers-1-0",
            "Today we're shipping Diffusers 1.0, a major milestone for the library "
            "with API stability guarantees, 3x faster inference, and first-class "
            "support for video models.",
            hours_ago=4,
        ),
        _make_entry(
            "Community spotlight: new open MoE model crosses 100M downloads",
            "https://huggingface.co/blog/moe-100m",
            "The Mixtral-style community models have crossed 100 million cumulative "
            "downloads on the Hub, reflecting growing adoption of MoE architectures.",
            hours_ago=22,
        ),
        _make_entry(
            "Five-year retrospective on transformers in vision",
            "https://huggingface.co/blog/vision-transformers-5yr",
            "A look back at how Vision Transformers evolved from ViT to today's "
            "multimodal foundation models.",
            hours_ago=48,  # older than 24h — should get filtered out
        ),
    ],
    ("TechCrunch AI", "industry", 1.0): [
        _make_entry(
            "Anthropic raises $4B at $50B valuation, sources say",
            "https://techcrunch.com/anthropic-4b-round",
            "Anthropic is closing a new funding round of approximately $4 billion "
            "at a $50 billion valuation, according to people familiar with the "
            "matter. Lead investor not yet disclosed.",
            hours_ago=6,
        ),
        _make_entry(
            "EU regulators open formal probe into OpenAI's enterprise terms",
            "https://techcrunch.com/eu-openai-probe",
            "The European Commission has opened a formal antitrust investigation "
            "into OpenAI's enterprise contracts, focusing on exclusivity and "
            "data-handling clauses.",
            hours_ago=10,
        ),
        _make_entry(
            "Local coffee shop unveils new oat milk latte",  # off-topic
            "https://techcrunch.com/coffee-shop",
            "A new oat milk latte hits San Francisco menus.",
            hours_ago=3,
        ),
    ],
}


def build_raw_entries() -> list[RawEntry]:
    out: list[RawEntry] = []
    for (name, category, weight), entries in SAMPLE_FEEDS.items():
        # Round-trip through feedparser the way the real fetcher does, to make
        # sure our normalize() handles feedparser's quirks correctly.
        fake_rss = _entries_to_rss(name, entries)
        parsed = feedparser.parse(fake_rss)
        for e in parsed.entries:
            out.append(
                RawEntry(
                    source_name=name,
                    source_category=category,
                    source_weight=weight,
                    entry=dict(e),
                )
            )
    return out


def _entries_to_rss(channel_title: str, entries: list[dict]) -> str:
    items = []
    for e in entries:
        items.append(
            f"<item><title>{e['title']}</title><link>{e['link']}</link>"
            f"<guid>{e['id']}</guid><pubDate>{e['published']}</pubDate>"
            f"<description><![CDATA[{e['summary']}]]></description></item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{channel_title}</title><link>http://example.com</link>"
        "<description>test</description>"
        + "".join(items)
        + "</channel></rss>"
    )


def main() -> None:
    raw = build_raw_entries()
    print(f"[test] built {len(raw)} synthetic entries across "
          f"{len(SAMPLE_FEEDS)} feeds")

    stories = pipeline.normalize(raw, max_summary_chars=280)
    print(f"[test] normalized to {len(stories)} stories")

    keywords = ["ai", "openai", "anthropic", "model", "moe", "transformer",
                "diffusers", "fine-tun"]
    stories = pipeline.filter_relevant(stories, keywords, window_hours=24)
    print(f"[test] {len(stories)} stories after relevance + age filter "
          f"(should drop 1 off-topic + 1 too-old = 2)")

    source_weights = {name: w for (name, _, w), _ in SAMPLE_FEEDS.items()}
    stories = pipeline.rank(stories, source_weights)
    stories = pipeline.cap(stories, 15)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with storage.connect(db_path) as conn:
            inserted = storage.upsert_stories(conn, stories)
        print(f"[test] sqlite: inserted {inserted} rows")

    output = render.render_plaintext(
        stories,
        edition="morning",
        category_order=["industry", "research", "tools", "policy"],
        total_scanned=len(raw),
    )
    print()
    print(output)


if __name__ == "__main__":
    main()
