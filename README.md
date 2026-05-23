# AI News Dashboard

A self-hosted, multi-user AI news aggregator with a web dashboard, magic-link auth, and an in-process digest scheduler. Fetches from curated RSS feeds (OpenAI, Hugging Face, TechCrunch, DeepMind, Wired, MIT Tech Review), runs them through a normalize → filter → rank → dedupe pipeline, and emails you a formatted digest at 6 AM and 8 PM in your timezone.

![dashboard](docs/screenshot.png)

---

## Quickstart (local dev)

```bash
# Clone and set up
git clone https://github.com/<you>/ai-news-aggregator.git
cd ai-news-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure credentials
cp .env.example .env
# Edit .env — fill in GMAIL_ADDRESS, GMAIL_APP_PASSWORD, TO_ADDRESS

# Start the dashboard
python3 run.py
```

Open [http://localhost:5000](http://localhost:5000).

On first visit you'll be prompted to sign in. Enter your email — a magic link will be sent to your inbox. Click it and you're in.

---

## CLI (still works)

```bash
# Morning digest — print to terminal
python3 -m core.main morning

# Morning digest — also email it
python3 -m core.main morning --send

# Evening edition
python3 -m core.main evening --send
```

---

## Features

### Auth — magic links
No passwords. Enter your email, receive a one-time sign-in link (valid 15 minutes). Anyone who signs up gets their own account with independent source and schedule preferences.

### Web dashboard
| Page | What it does |
|------|-------------|
| `/feed` | Live story feed for your enabled sources, with an HTMX refresh button |
| `/settings` | Toggle sources, enable/disable morning + evening digest, set timezone |
| `/preview` | See exactly what the next email will look like (in an iframe) |
| `/archive` | Browse every digest you've been sent |

### In-process scheduler (APScheduler)
- **Hourly** — refreshes the global story cache from all sources
- **Every minute** — checks if it's 6:00 AM or 8:00 PM in each user's timezone, and sends their personalized digest if so
- Idempotent: won't double-send if the server restarts mid-minute
- Disable with `ENABLE_SCHEDULER=0` if you want a separate cron process

---

## Deploying to production

See **[DEPLOY.md](DEPLOY.md)** for step-by-step instructions for Render and Fly.io.

Short version:
1. Push to GitHub
2. Create a Render Web Service (auto-detects Dockerfile)
3. Add environment variables (see `.env.example`)
4. Add a Render Postgres database, paste the URL into `DATABASE_URL`
5. Deploy

---

## Project layout

```
ai-news-aggregator/
├── core/                  ← pipeline (fetch, normalize, rank, dedupe, render, deliver)
│   └── templates/digest.html.j2
├── app/                   ← Flask web layer
│   ├── __init__.py        ← create_app() factory
│   ├── models.py          ← SQLAlchemy: User, MagicLink, UserSettings, UserSource, Digest
│   ├── auth.py            ← magic-link login flow + Flask-Login
│   ├── routes.py          ← all web routes
│   ├── scheduler.py       ← APScheduler jobs
│   └── templates/         ← Jinja2 + Tailwind (CDN) + HTMX (CDN)
├── config/
│   ├── sources.yaml       ← RSS source list
│   └── settings.yaml      ← global defaults
├── tests/                 ← pytest suite
├── run.py                 ← `python3 run.py` dev server
├── Dockerfile             ← multi-stage Python 3.11 image
├── gunicorn_conf.py
├── .env.example
└── DEPLOY.md
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_ADDRESS` | — | Gmail account for sending |
| `GMAIL_APP_PASSWORD` | — | 16-char Gmail App Password |
| `TO_ADDRESS` | — | Recipient email (CLI mode) |
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret — change in prod! |
| `DATABASE_URL` | `sqlite:///data.db` | SQLite or `postgres://...` |
| `FLASK_ENV` | `development` | Set to `production` in prod |
| `ENABLE_SCHEDULER` | `1` | Set to `0` to disable APScheduler |
| `PORT` | `5000` / `8080` | Server port (Render/Fly inject this) |
