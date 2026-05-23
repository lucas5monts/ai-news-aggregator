# Install & Run on Your Mac — Phase 1

These steps put the project at `~/Desktop/ai-news-aggregator/` and run a real digest against live RSS feeds.

## 1. Copy the project to your Desktop

If you've already downloaded the project folder from Claude's outputs, drag it to your Desktop. Otherwise, in your terminal:

```bash
# (only if you have the folder somewhere else first)
mv ~/Downloads/ai-news-aggregator ~/Desktop/
cd ~/Desktop/ai-news-aggregator
```

## 2. Install Python dependencies

You need Python 3.11 or newer. Check with `python3 --version`. If you're on macOS, you almost certainly already have it.

```bash
cd ~/Desktop/ai-news-aggregator
python3 -m pip install -r requirements.txt
```

(If pip complains about "externally-managed-environment", add `--break-system-packages` or use a venv — `python3 -m venv .venv && source .venv/bin/activate` first.)

## 3. Run the morning digest

```bash
cd ~/Desktop/ai-news-aggregator
python3 -m src.main morning
```

You should see something like:

```
20:14:02  INFO  main  edition=morning  window=24h  max=15
20:14:02  INFO  src.fetch  fetched OpenAI News — 12 entries in 340ms
20:14:02  INFO  src.fetch  fetched Hugging Face Blog — 20 entries in 410ms
20:14:03  INFO  src.fetch  fetched TechCrunch AI — 25 entries in 520ms
...
════════════════════════════════════════════════════════════
AI NEWS DAILY · MORNING · Thu May 21 · 8:14 PM
════════════════════════════════════════════════════════════
INDUSTRY (5)
─────────────
▸ [actual story title here]
  ...
```

A `data.db` SQLite file gets created in the project folder — that's where seen stories are tracked so the evening edition can skip ones already in the morning digest.

## 4. Verify the test passes (sanity check, optional)

```bash
python3 tests/test_pipeline_with_sample.py
```

This runs the full pipeline against canned data — no network needed. Useful if real feeds are flaky and you want to confirm the code itself is OK.

## What's NOT in Phase 1 yet

- Email delivery (Phase 3)
- Cross-source dedupe (Phase 2)
- `launchd` scheduling (Phase 4)
- The other 4 RSS sources beyond the starting 3 (Phase 2)

These come next once you've seen the terminal digest and decided you like the shape.
