# AI News Aggregator

A personal, zero-cost AI news digest that emails you a curated brief at 6:00 AM and 8:00 PM.

## Status

- ✅ **Phase 1** — Walking skeleton: 3 RSS feeds → SQLite → terminal digest
- ✅ **Phase 2** — Full source list + fuzzy-match dedupe + ranking
- ✅ **Phase 3** — HTML email + Gmail SMTP delivery
- ⏳ Phase 4 — launchd scheduling + 8 PM "what you missed" edition
- ⏳ Phase 5 — (optional) Ollama local LLM summaries

## Quickstart

```bash
# install deps (one-time)
pip install -r requirements.txt

# run morning digest — prints to terminal, no email sent
python3 -m src.main morning

# run AND email the digest to yourself
python3 -m src.main morning --send

# evening edition (12h window)
python3 -m src.main evening --send
```

### Setting up email (--send)

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Follow the "Gmail App Password" instructions in `.env.example` to generate
   a 16-character app password, then fill in the three variables:
   ```
   GMAIL_ADDRESS=you@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   TO_ADDRESS=you@gmail.com
   ```
3. Test: `python3 -m src.main morning --send`

## Layout

```
ai-news-aggregator/
├── config/
│   ├── sources.yaml           # which RSS feeds to scrape
│   └── settings.yaml          # max stories, time window, keywords
├── src/
│   ├── main.py                # entrypoint (--send flag lives here)
│   ├── fetch.py               # RSS pulling
│   ├── pipeline.py            # normalize + filter + dedupe + rank
│   ├── storage.py             # SQLite helpers
│   ├── render.py              # plain-text + HTML digest
│   ├── deliver.py             # Gmail SMTP delivery
│   └── templates/
│       └── digest.html.j2     # Jinja2 HTML email template
├── tests/
│   ├── test_pipeline_with_sample.py
│   └── test_render_html.py
├── .env.example               # copy to .env and fill in credentials
├── requirements.txt
└── data.db                    # auto-created
```
