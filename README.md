# AI News Dashboard

A self-hosted AI news aggregator with a public web dashboard and email newsletter. Fetches from curated RSS feeds (OpenAI, Hugging Face, TechCrunch, DeepMind, Wired, MIT Tech Review), runs them through a normalize → filter → rank → dedupe pipeline, and emails subscribers a formatted digest at 6 AM and 8 PM in their timezone.

---

## Quickstart (local dev)

```bash
git clone https://github.com/<you>/ai-news-aggregator.git
cd ai-news-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — fill in GMAIL_ADDRESS, GMAIL_APP_PASSWORD (needed for sending digests)

PORT=8080 python3 run.py
```

Open **http://127.0.0.1:8080/feed** (use `127.0.0.1`, not `localhost` — macOS AirPlay uses port 5000).

No login required. Browse the feed, then subscribe at `/subscribe` to get digests by email.

For a shorter Mac-only walkthrough, see **[INSTALL.md](INSTALL.md)**.

---

## CLI

Run the pipeline without the web server:

```bash
python3 -m core.main morning              # last 24h, print to terminal
python3 -m core.main morning --send       # email it (uses TO_ADDRESS in .env)
python3 -m core.main evening --send       # last 12h, email evening edition
python3 -m core.main morning --verbose    # debug logging
python3 -m core.main morning --window-hours 48   # override time window
```

---

## Web pages

| Page | What it does |
|------|-------------|
| `/` | Redirects to `/feed` |
| `/feed` | Live story feed with images, HTMX refresh |
| `/preview` | See exactly what the email digest looks like |
| `/subscribe` | Sign up with email, timezone, and morning/evening toggles |

State-changing forms (subscribe, feed refresh) are CSRF-protected via Flask-WTF.

---

## Scheduler (APScheduler)

Started automatically when you run `python3 run.py` (or gunicorn with `ENABLE_SCHEDULER=1`):

- **Hourly** — refreshes the global story cache in `data.db`
- **Every minute** — sends morning (6 AM) / evening (8 PM) digests to subscribers in their timezone
- Disable with `ENABLE_SCHEDULER=0`

---

## Tests

```bash
python3 -m pytest tests/ -q
```

---

## Deploying to production

See **[DEPLOY.md](DEPLOY.md)** for Render and Fly.io instructions.

Production uses gunicorn:

```bash
gunicorn -c gunicorn_conf.py run:app
```

---

## Project layout

```
ai-news-aggregator/
├── core/                      ← RSS pipeline
│   ├── fetch.py               ← pull all sources
│   ├── pipeline.py            ← normalize, filter, rank, dedupe, cap
│   ├── images.py              ← enrich stories with article images
│   ├── render.py              ← HTML + plaintext digest rendering
│   ├── deliver.py             ← Gmail SMTP delivery
│   ├── storage.py             ← story cache (SQLite, raw SQL)
│   ├── main.py                ← CLI entrypoint
│   └── templates/digest.html.j2
├── app/                       ← Flask web layer
│   ├── __init__.py            ← app factory, DB init, CSRF
│   ├── models.py              ← users, settings, digest history (SQLAlchemy)
│   ├── routes.py              ← feed + preview routes
│   ├── subscriptions.py       ← newsletter signup (no login)
│   ├── scheduler.py           ← APScheduler jobs
│   ├── template_filters.py    ← Jinja filters (e.g. time_ago)
│   └── templates/             ← Jinja2 + Tailwind (CDN) + HTMX (CDN)
├── config/
│   ├── sources.yaml           ← RSS source list
│   └── settings.yaml          ← global defaults
├── tests/
├── .env.example
├── run.py                     ← dev server
├── gunicorn_conf.py           ← production server config
├── Dockerfile
├── INSTALL.md                 ← short Mac install guide
└── DEPLOY.md
```

**Storage:** subscriber data and digest logs live in the SQLAlchemy database (`DATABASE_URL`). The global story cache is a separate SQLite file (`data.db`) managed by `core/storage.py`.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_ADDRESS` | — | Gmail account for sending |
| `GMAIL_APP_PASSWORD` | — | 16-char Gmail App Password |
| `TO_ADDRESS` | — | Recipient email (CLI `--send` only) |
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret — change in prod! |
| `DATABASE_URL` | `sqlite:///data.db` | SQLite or `postgres://...` |
| `FLASK_ENV` | `development` | Set to `production` in prod |
| `ENABLE_SCHEDULER` | `1` | Set to `0` to disable APScheduler |
| `PORT` | `5000` in code; `8080` in `.env.example` | Server port — use `8080` locally on macOS |
