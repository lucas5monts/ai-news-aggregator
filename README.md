# AI News Dashboard

A self-hosted general news aggregator with a public web dashboard and email newsletter. Fetches from curated RSS feeds (world, US, tech, AI, business, science, politics, sports), runs them through a normalize → filter → rank → dedupe → cluster pipeline, and emails subscribers a formatted digest on their chosen schedule (morning/evening presets plus optional custom times). Subscribers with interest topics set get LLM-scored, personalized stories on the feed and in their digest.

---

## Quickstart (local dev)

```bash
git clone https://github.com/<you>/ai-news-aggregator.git
cd ai-news-aggregator
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — fill in GMAIL_ADDRESS, GMAIL_APP_PASSWORD (needed for sending digests)
# Optional: ANTHROPIC_API_KEY for LLM topic personalization (without it, feed/digest show the full general feed)

PORT=8080 python3 run.py
```

Open **http://127.0.0.1:8080/feed** (use `127.0.0.1`, not `localhost` — macOS AirPlay uses port 5000).

**No login required to browse.** Create an account at `/subscribe` (email + password) to receive digests and personalize the feed. Log in at `/login` to manage preferences at `/preferences`.

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
| `/feed` | Live story feed with images, category/topic filters, HTMX refresh; personalized when logged in |
| `/feed/refresh` | HTMX partial refresh (POST) |
| `/search` | Full-text search over cached stories (SQLite FTS; requires `DATABASE_URL` pointing at SQLite) |
| `/preview` | Preview the email digest; filter by source, category, time window, and story count |
| `/click/<story_id>` | Record a click, then redirect to the article |
| `/subscribe` | Create account — email, password, interests, timezone, delivery schedule |
| `/login` | Log in with email + password |
| `/preferences` | Edit interests, schedule, sources, blocked keywords, and custom RSS feeds (**login required**) |
| `/bookmarks` | Saved stories (**login required**) |
| `/bookmark/<story_id>` | Toggle bookmark (POST, **login required**) |
| `/digests` | Browse past email digests (**login required**) |
| `/digests/<id>` | View a single archived digest (**login required**) |
| `/ref/<code>` | Referral landing — sets a cookie, redirects to `/subscribe` |
| `/unsubscribe/<token>` | One-click unsubscribe from digest emails (token link, no login) |

### Authentication

- **Registration** happens on `/subscribe`: set a password (8–128 characters), pick topics and delivery times, and you're logged in automatically. A welcome email is sent immediately after signup.
- **Sessions** use Flask-Login (Werkzeug PBKDF2 password hashing). Optional “Keep me logged in” on login.
- **Logout** is POST-only with CSRF protection (nav button submits a form, not a GET link).
- **Feed, preview, and search stay public.** Personalization uses your session when logged in, or a signed `subscriber_id` cookie after subscribe.
- **Existing subscribers** created before passwords were added must set a password via a future reset flow, or re-register once that exists.

State-changing actions (subscribe, login, logout, preferences, feed refresh, bookmarks) are CSRF-protected via Flask-WTF. Sensitive routes are rate-limited with Flask-Limiter.

---

## Scheduler (APScheduler)

Started automatically when you run `python3 run.py` (or gunicorn with `ENABLE_SCHEDULER=1`):

- **Hourly** — refreshes the global story cache in `data.db`
- **Every minute** — sends morning / evening / custom-time digests to subscribers in their timezone
- **Daily at 09:00 UTC** — day-3 onboarding nudge to users who haven't set interest topics yet
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

In production (`FLASK_ENV=production`), set a strong `SECRET_KEY` — it signs sessions, CSRF tokens, and the subscriber cookie. Session and subscriber cookies are sent with `Secure` over HTTPS. Set `REDIS_URL` when running multiple gunicorn workers so rate-limit state is shared.

---

## Project layout

```
ai-news-aggregator/
├── core/                      ← RSS pipeline
│   ├── fetch.py               ← pull all sources
│   ├── pipeline.py            ← normalize, filter, rank, dedupe, cluster, cap
│   ├── relevance.py           ← LLM topic scoring for personalization
│   ├── images.py              ← enrich stories with article images
│   ├── render.py              ← HTML + plaintext digest rendering
│   ├── deliver.py             ← Gmail SMTP delivery (+ unsubscribe link)
│   ├── storage.py             ← story cache (SQLite, raw SQL)
│   ├── main.py                ← CLI entrypoint
│   └── templates/digest.html.j2
├── app/                       ← Flask web layer
│   ├── __init__.py            ← app factory, DB init, CSRF, Flask-Login
│   ├── models.py              ← users, settings, topics, digests, bookmarks, clicks
│   ├── auth.py                ← login / logout
│   ├── routes.py              ← feed, preview, search, click tracking
│   ├── subscriptions.py       ← registration, referral, unsubscribe
│   ├── preferences.py         ← subscriber settings (login required)
│   ├── bookmarks.py           ← save / list bookmarked stories
│   ├── digest_archive.py      ← browse past email digests
│   ├── onboarding.py          ← welcome email + day-3 topic nudge
│   ├── subscriber_cookie.py   ← signed cookie for feed personalization
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

**Storage:** subscriber data, digest history (including full HTML blobs for the archive), bookmarks, and click logs live in the SQLAlchemy database (`DATABASE_URL`). The global story cache is a separate SQLite file (`data.db`) managed by `core/storage.py`.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_ADDRESS` | — | Gmail account for sending |
| `GMAIL_APP_PASSWORD` | — | 16-char Gmail App Password |
| `TO_ADDRESS` | — | Recipient email (CLI `--send` only) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key for LLM topic personalization; without it, subscribers get the unfiltered general feed |
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret — **required in prod**; also signs CSRF and subscriber cookies |
| `DATABASE_URL` | `sqlite:///data.db` | SQLite or `postgres://...` |
| `FLASK_ENV` | `development` | Set to `production` in prod |
| `ENABLE_SCHEDULER` | `1` | Set to `0` to disable APScheduler |
| `APP_BASE_URL` | — | Public base URL for unsubscribe and referral links in emails (e.g. `https://your-app.onrender.com`) |
| `REDIS_URL` | — | Redis URL for shared rate-limiter state in production; omit for in-memory (fine for local dev) |
| `PORT` | `5000` in code; `8080` in `.env.example` | Server port — use `8080` locally on macOS |
