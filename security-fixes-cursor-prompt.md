# Security Fixes — AI News Aggregator

Fix the following security vulnerabilities in this Flask app. Do them all in one pass.

---

## 1. Unsafe story URLs (XSS) — HIGH
**Files:** `app/templates/_macros.html`

Story URLs come from untrusted RSS feeds and are rendered directly into `href` attributes. Jinja2 autoescaping only escapes HTML special chars (`<`, `>`, `&`, `"`, `'`), so a `javascript:` URL passes through untouched and becomes a valid XSS vector.

**Fix:** Add a Jinja2 filter `safe_url` in `app/template_filters.py` that returns the URL only if its scheme is `http` or `https`, otherwise returns `#`. Apply it to every `href="{{ story.url }}"` occurrence in `_macros.html` (there are three: `story_card`, `hero_card`, `story_list_item`).

```python
# In app/template_filters.py
from urllib.parse import urlparse

def safe_url(url: str) -> str:
    """Return url only if scheme is http/https, else '#'."""
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https"):
            return url
    except Exception:
        pass
    return "#"
```

Register it in `app/__init__.py`:
```python
from .template_filters import card_image, time_ago, safe_url
app.jinja_env.filters["safe_url"] = safe_url
```

Usage in `_macros.html`:
```html
<a href="{{ story.url | safe_url }}" target="_blank" rel="noopener noreferrer" ...>
```

---

## 2. Weak SECRET_KEY fallback — HIGH
**File:** `app/__init__.py`, line 22

```python
# CURRENT (insecure fallback):
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
```

If `SECRET_KEY` is not set in the environment, Flask uses a predictable key, allowing anyone to forge signed session cookies.

**Fix:** Raise a hard error in production if the key is missing or still the default:

```python
secret_key = os.environ.get("SECRET_KEY", "")
flask_env = os.environ.get("FLASK_ENV", "development")

if flask_env == "production":
    if not secret_key or secret_key in ("dev-secret-change-me", "change-me-to-a-long-random-string"):
        raise RuntimeError(
            "SECRET_KEY env var is not set or is still the default placeholder. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

app.config["SECRET_KEY"] = secret_key or "dev-secret-change-me"
```

---

## 3. SSRF in image fetching — HIGH
**File:** `core/images.py`, function `_fetch_og_one`

The app fetches article URLs from RSS feeds to scrape og:image metadata. A malicious RSS feed could supply internal IP addresses (e.g., `http://169.254.169.254/latest/meta-data/` for AWS metadata, or `http://127.0.0.1:...`) to make the server send requests to internal services.

**Fix:** Add an IP allowlist check before fetching. Resolve the hostname and block private/loopback ranges:

```python
import ipaddress
import socket
from urllib.parse import urlparse

def _is_safe_url(url: str) -> bool:
    """Return False if the URL resolves to a private/loopback/link-local IP."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.hostname
        if not host:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(host))
        return ip.is_global and not ip.is_private and not ip.is_loopback and not ip.is_link_local and not ip.is_reserved
    except Exception:
        return False
```

Call `_is_safe_url(article_url)` at the top of `_fetch_og_one` and return `None` immediately if it returns `False`.

---

## 4. No rate limiting — HIGH
**Files:** `app/subscriptions.py` (`/subscribe`), `app/routes.py` (`/feed/refresh`)

`/subscribe` has no throttle — a bot can create thousands of subscriber records. `/feed/refresh` triggers a full pipeline fetch (multiple HTTP requests to external sources) on every POST, making it trivially cheap to DoS.

**Fix:** Install `Flask-Limiter` and add rate limits:

```bash
pip install Flask-Limiter
```

In `app/__init__.py`, initialize the limiter:

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")
```

Export it so blueprints can import it, or use the extension pattern. Then decorate the routes:

```python
# app/subscriptions.py
from app import limiter  # or however you export it

@subscriptions_bp.route("/subscribe", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour")
def subscribe():
    ...
```

```python
# app/routes.py
@main_bp.route("/feed/refresh", methods=["POST"])
@limiter.limit("2 per minute")
def feed_refresh():
    ...
```

---

## 5. Weak email validation — MEDIUM
**File:** `app/subscriptions.py`, line 72

```python
# CURRENT:
if not email or "@" not in email:
```

This accepts `a@b`, `@`, `x@`, etc.

**Fix:** Use a stricter regex:

```python
import re
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

if not email or not _EMAIL_RE.match(email):
    flash("Please enter a valid email address.", "error")
    return render_template("subscribe.html"), 400
```

Also cap the length: `if len(email) > 254`.

---

## 6. Timezone not validated — MEDIUM
**File:** `app/subscriptions.py`, line 78

The timezone string from the form is stored in the DB as-is without checking it's a valid IANA timezone. An attacker can store arbitrary long strings in the `user_settings.timezone` column, and invalid timezones silently fall back to UTC in `scheduler.py` (causing misdelivery with no error to the user).

**Fix:** Validate against `zoneinfo.available_timezones()` before storing:

```python
import zoneinfo

VALID_TIMEZONES = zoneinfo.available_timezones()
DEFAULT_TZ = "America/Los_Angeles"

timezone_input = request.form.get("timezone", DEFAULT_TZ).strip()
if timezone_input not in VALID_TIMEZONES:
    timezone_input = DEFAULT_TZ
```

---

## 7. Missing security headers — MEDIUM
**File:** `app/__init__.py`

No Content-Security-Policy, X-Frame-Options, or X-Content-Type-Options headers are set. Without a CSP, any XSS has full impact.

**Fix:** Add a `after_request` hook in `create_app`:

```python
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if flask_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: allow scripts only from known CDNs (tailwind, htmx, lucide, fonts)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "frame-src 'none';"
    )
    return response
```

Note: `'unsafe-inline'` is needed because `base.html` uses inline `<script>` blocks. Once those are moved to external `.js` files you can tighten the CSP further.

---

## 8. No request body size limit — LOW
**File:** `app/__init__.py`

Flask accepts arbitrarily large request bodies by default.

**Fix:** Add to `create_app`:

```python
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB
```

---

## Summary of files to touch

| File | Changes |
|---|---|
| `app/__init__.py` | SECRET_KEY validation, security headers, MAX_CONTENT_LENGTH, register safe_url filter, init limiter |
| `app/template_filters.py` | Add `safe_url` filter |
| `app/templates/_macros.html` | Apply `safe_url` to all 3 `story.url` hrefs |
| `app/subscriptions.py` | Stricter email regex, timezone validation, rate limit decorator |
| `app/routes.py` | Rate limit on `/feed/refresh` |
| `core/images.py` | SSRF check in `_fetch_og_one` |
| `requirements.txt` | Add `Flask-Limiter` |
