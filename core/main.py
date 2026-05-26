"""AI News Aggregator — CLI entrypoint.

Usage:
    python -m core.main morning         # last 24h, print to terminal
    python -m core.main morning --send  # same + email digest via Gmail
    python -m core.main evening         # last 12h
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import deliver, fetch, pipeline, render, storage

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EDITION_WINDOWS = {
    "morning": 24,
    "evening": 12,
}


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    # quiet down http chatter unless --verbose
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="AI news digest builder")
    parser.add_argument(
        "edition",
        choices=list(EDITION_WINDOWS),
        help="morning (24h window) or evening (12h)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show debug logging"
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=None,
        help="Override the default time window for this edition",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the digest via Gmail SMTP (requires .env with credentials)",
    )
    args = parser.parse_args()
    _setup_logging(args.verbose)
    log = logging.getLogger("main")

    sources_cfg = _load_yaml(PROJECT_ROOT / "config" / "sources.yaml")
    settings = _load_yaml(PROJECT_ROOT / "config" / "settings.yaml")

    window = args.window_hours or EDITION_WINDOWS[args.edition]
    keywords = settings.get("relevance_keywords") or []
    max_stories = int(settings.get("max_stories", 15))
    category_order = settings.get("digest", {}).get(
        "category_order", ["industry", "research", "tools", "policy"]
    )
    max_summary_chars = int(settings.get("digest", {}).get("max_summary_chars", 280))

    log.info("edition=%s  window=%dh  max=%d", args.edition, window, max_stories)

    # 1. fetch
    raw = fetch.fetch_all(sources_cfg["sources"])
    log.info("fetched %d total entries from %d sources", len(raw), len(sources_cfg["sources"]))

    # 2. normalize
    stories = pipeline.normalize(raw, max_summary_chars=max_summary_chars)
    total_scanned = len(stories)

    # 3. filter
    stories = pipeline.filter_relevant(stories, keywords, window)

    # 4. rank
    source_weights = {s["name"]: float(s.get("weight", 1.0)) for s in sources_cfg["sources"]}
    stories = pipeline.rank(stories, source_weights)

    # 5. dedupe
    stories = pipeline.dedupe(stories)

    # 6. cap
    stories = pipeline.cap(stories, max_stories)

    # 7. persist
    db_path = PROJECT_ROOT / "data.db"
    with storage.connect(db_path) as conn:
        inserted = storage.upsert_stories(conn, stories)
    log.info("stored %d new stories (total in digest: %d)", inserted, len(stories))

    # 8. render plaintext (always)
    output = render.render_plaintext(
        stories,
        edition=args.edition,
        category_order=category_order,
        total_scanned=total_scanned,
    )
    print()
    print(output)

    # 9. optional email delivery
    if args.send:
        email_cfg = deliver.load_email_config()
        if "TO_ADDRESS" not in email_cfg:
            raise RuntimeError(
                "Missing required environment variable: TO_ADDRESS.\n"
                "Copy .env.example to .env and set TO_ADDRESS to the delivery address."
            )
        subject = deliver.build_subject(args.edition, len(stories))
        html = render.render_html(
            stories,
            edition=args.edition,
            category_order=category_order,
            total_scanned=total_scanned,
        )
        deliver.send_digest(
            subject=subject,
            plaintext=output,
            html=html,
            to_address=email_cfg["TO_ADDRESS"],
            from_address=email_cfg["GMAIL_ADDRESS"],
            app_password=email_cfg["GMAIL_APP_PASSWORD"],
        )
        sent_at = datetime.now(timezone.utc)
        with storage.connect(db_path) as conn:
            updated = storage.mark_sent(conn, [s.id for s in stories], sent_at)
        log.info("marked %d stories as sent", updated)

    return 0


if __name__ == "__main__":
    sys.exit(main())
