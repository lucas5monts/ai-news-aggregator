# AI News Aggregator

A personal, zero-cost AI news digest that emails you a curated brief at 6:00 AM and 8:00 PM.

## Status

- ✅ **Phase 1** — Walking skeleton: 3 RSS feeds → SQLite → terminal digest
- ⏳ Phase 2 — Full source list + fuzzy-match dedupe + ranking
- ⏳ Phase 3 — HTML email + Gmail SMTP delivery
- ⏳ Phase 4 — launchd scheduling + 8 PM "what you missed" edition
- ⏳ Phase 5 — (optional) Ollama local LLM summaries

## Quickstart (Phase 1)

```bash
# install deps (one-time)
pip install -r requirements.txt

# run morning digest (prints to terminal)
python -m src.main morning
```

## Layout

```
ai-news-aggregator/
├── config/
│   ├── sources.yaml      # which RSS feeds to scrape
│   └── settings.yaml     # max stories, time window, keywords
├── src/
│   ├── main.py           # entrypoint
│   ├── fetch.py          # RSS pulling
│   ├── pipeline.py       # normalize + filter + (later) dedupe + rank
│   ├── storage.py        # SQLite helpers
│   └── render.py         # plain-text + (later) HTML digest
├── requirements.txt
└── data.db               # auto-created
```
