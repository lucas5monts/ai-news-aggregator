# Deployment Guide

> **Security note — CSRF protection:** State-changing forms (subscribe, feed refresh)
> are protected by Flask-WTF CSRF tokens.

## Quick deploy to Render

Render is the simplest path: it detects your Dockerfile automatically.

### Prerequisites

- A GitHub account with this repo pushed
- A Render account (free tier works for small usage)

### Steps

1. **Push to GitHub**
   ```bash
   git remote add origin https://github.com/<you>/ai-news-aggregator.git
   git push -u origin main
   ```

2. **Create a new Web Service on Render**
   - Go to [render.com/dashboard](https://render.com/dashboard) → **New → Web Service**
   - Connect your GitHub repo
   - Render will auto-detect the `Dockerfile` — no extra config needed

3. **Set environment variables** in Render's dashboard (Environment tab):
   ```
   GMAIL_ADDRESS=you@gmail.com
   GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
   TO_ADDRESS=you@gmail.com
   SECRET_KEY=<a long random string>
   FLASK_ENV=production
   ENABLE_SCHEDULER=1
   PORT=8080
   ```
   Generate a secret key:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

4. **Add a Render PostgreSQL database**
   - In your Render dashboard: **New → PostgreSQL**
   - After creation, copy the **Internal Database URL**
   - Paste it into your Web Service's `DATABASE_URL` environment variable

5. **Deploy**
   - Click **Deploy** (or push a new commit — Render auto-deploys on push)
   - First deploy takes ~2–3 minutes while building the Docker image

6. **Subscribe**
   - Open `https://<your-service>.onrender.com/feed`
   - Go to `/subscribe`, enter your email and delivery preferences
   - Digests arrive at 6 AM / 8 PM in your chosen timezone

---

## Alternative: Fly.io

Fly.io gives you more control and better free-tier limits for persistent apps.

```bash
# Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login

# Launch (creates fly.toml — review and commit it)
fly launch

# Set secrets
fly secrets set \
  GMAIL_ADDRESS=you@gmail.com \
  GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx" \
  TO_ADDRESS=you@gmail.com \
  SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  FLASK_ENV=production \
  ENABLE_SCHEDULER=1

# Create a Postgres cluster (optional — SQLite works fine for personal use)
fly postgres create --name ai-news-db
fly postgres attach ai-news-db

# Deploy
fly deploy
```

Fly injects `DATABASE_URL` automatically after `fly postgres attach`.
The Dockerfile's `EXPOSE 8080` and `CMD gunicorn ...` are read directly by Fly.

---

## Running locally with Docker

```bash
docker build -t ai-news-dashboard .

docker run --rm -p 8080:8080 \
  -e SECRET_KEY=localdev \
  -e FLASK_ENV=development \
  -e GMAIL_ADDRESS=you@gmail.com \
  -e GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx" \
  -e TO_ADDRESS=you@gmail.com \
  -e ENABLE_SCHEDULER=0 \
  ai-news-dashboard
```

Open `http://localhost:8080`.

---

## Production checklist

- [ ] `SECRET_KEY` is set to a long, random, secret value
- [ ] `FLASK_ENV=production` (enables secure cookies)
- [ ] `DATABASE_URL` points to a managed Postgres (not SQLite)
- [ ] HTTPS is enabled (Render/Fly do this automatically)
- [ ] GMAIL_APP_PASSWORD is stored as a secret, not committed to git
- [ ] (Future) Add Flask-WTF CSRF protection
