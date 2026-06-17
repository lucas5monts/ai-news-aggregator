# Security Fixes — Auth Layer

Three issues to fix across `app/auth.py`, `app/preferences.py`, and `app/subscriber_cookie.py`.

---

## Fix 1: Logout must be POST (CSRF protection)

**File: `app/auth.py`**

A GET `/logout` route can be triggered by any cross-site resource (an `<img src="/logout">` in an RSS story would silently log the user out when the feed page loads). Logout must require a POST with a CSRF token.

Change the logout route from GET to POST-only:

```python
@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    from flask import make_response
    from .subscriber_cookie import clear_subscriber_cookie
    log.info("logout: user_id=%s", current_user.id)
    logout_user()
    flash("You've been logged out.", "info")
    resp = make_response(redirect(url_for("main.feed")))
    clear_subscriber_cookie(resp)
    return resp
```

**File: `app/templates/base.html`** (and any other template with a logout link)

Replace the `<a href="/logout">` link with a small form:

```html
<form method="POST" action="{{ url_for('auth.logout') }}" style="display:inline">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
  <button type="submit"
          class="text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 bg-transparent border-0 cursor-pointer p-0">
    Log out
  </button>
</form>
```

---

## Fix 2: Flip decorator order in preferences (rate limit before login check)

**File: `app/preferences.py`**

`@login_required` is currently the outermost decorator, so unauthenticated requests redirect before the limiter ever runs — effectively bypassing rate limiting for the endpoint.

Swap the order so the limiter is outermost:

```python
@preferences_bp.route("/preferences", methods=["GET", "POST"])
@limiter.limit("10 per minute; 60 per hour")   # ← must be outer (runs first)
@login_required
def preferences():
    ...
```

---

## Fix 3: Clear subscriber cookie on logout

This is already handled in Fix 1 above — `clear_subscriber_cookie(resp)` is called in the new `logout()` handler. Just make sure the import is present.

---

## Fix 4 (minor): Set `secure=True` on subscriber cookie in production

**File: `app/subscriber_cookie.py`**

The subscriber cookie doesn't set `secure=True`, inconsistent with the Flask-Login session cookie which gets `SESSION_COOKIE_SECURE = True` in production. Fix:

```python
def set_subscriber_cookie(response, user_id: int) -> None:
    """Attach a signed HttpOnly cookie identifying *user_id*."""
    from flask import current_app
    secure = current_app.config.get("SESSION_COOKIE_SECURE", False)
    token = _serializer().dumps(user_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=secure,
    )
```

---

## Files to touch

| File | Change |
|---|---|
| `app/auth.py` | Change `logout` to POST-only; call `clear_subscriber_cookie` |
| `app/preferences.py` | Swap `@limiter.limit` and `@login_required` order |
| `app/subscriber_cookie.py` | Add `secure=secure` to `set_cookie` call |
| `app/templates/base.html` | Replace logout `<a>` with a `<form method="POST">` |
