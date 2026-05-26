# AI News Dashboard

A self-hosted AI news aggregator with a public web dashboard and email newsletter. Fetches from curated RSS feeds (OpenAI, Hugging Face, TechCrunch, DeepMind, Wired, MIT Tech Review), runs them through a normalize → filter → rank → dedupe pipeline, and emails subscribers a formatted digest at 6 AM and 8 PM in their timezone.

![dashboard](docs/screenshot.png)

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

Open **http://127.0.0.1:8080** (use `127.0.0.1`, not `localhost` — macOS AirPlay uses port 5000).

No login required. Browse the feed, then subscribe at `/subscribe` to get the daily digest by email.

---

## CLI

```bash
python3 -m core.main morning          # print digest to terminal
python3 -m core.main morning --send   # email it (uses TO_ADDRESS in .env)
python3 -m core.main evening --send   # evening edition
```

---

## Web pages

| Page | What it does |
|------|-------------|
| `/feed` | Live story feed with images, HTMX refresh |
| `/preview` | See exactly what the email digest looks like |
| `/subscribe` | Enter email + schedule to receive digests |

---

## Scheduler (APScheduler)

- **Hourly** — refreshes the global story cache
- **Every minute** — sends morning (6 AM) / evening (8 PM) digests to subscribers in their timezone
- Disable with `ENABLE_SCHEDULER=0`

---

## Deploying to production

See **[DEPLOY.md](DEPLOY.md)** for Render and Fly.io instructions.

---

## Project layout

```
ai-news-aggregator/
├── core/                  ← pipeline (fetch, normalize, rank, dedupe, render, deliver, images)
│   └── templates/digest.html.j2
├── app/                   ← Flask web layer
│   ├── subscriptions.py   ← newsletter signup (no login)
│   ├── routes.py          ← feed + preview routes
│   ├── scheduler.py       ← APScheduler jobs
│   └── templates/         ← Jinja2 + Tailwind (CDN) + HTMX (CDN)
├── config/
│   ├── sources.yaml       ← RSS source list
│   └── settings.yaml      ← global defaults
├── tests/
├── run.py                 ← dev server
├── Dockerfile
└── DEPLOY.md
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_ADDRESS` | — | Gmail account for sending |
| `GMAIL_APP_PASSWORD` | — | 16-char Gmail App Password |
| `TO_ADDRESS` | — | Recipient email (CLI mode only) |
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret — change in prod! |
| `DATABASE_URL` | `sqlite:///data.db` | SQLite or `postgres://...` |
| `FLASK_ENV` | `development` | Set to `production` in prod |
| `ENABLE_SCHEDULER` | `1` | Set to `0` to disable APScheduler |
| `PORT` | `5000` | Server port (use `8080` locally on macOS) |
