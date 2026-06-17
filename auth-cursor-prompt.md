# Feature: Email/Password Authentication

Add simple email + password login using Flask-Login. Werkzeug (already installed) handles password hashing. The subscribe form becomes the registration form — setting a password on first subscribe. Preferences switches from "re-enter your email" to proper login sessions.

---

## 1. Install Flask-Login

```
pip install flask-login
```

Add `flask-login` to `requirements.txt`.

---

## 2. Update the User Model — `app/models.py`

Add `password_hash` and Flask-Login's `UserMixin`:

```python
from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)   # nullable for migration
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    unsubscribe_token = db.Column(
        db.String(64), unique=True, nullable=False,
        default=lambda: secrets.token_urlsafe(32)
    )

    # relationships stay the same
    settings = db.relationship("UserSettings", uselist=False, back_populates="user", cascade="all, delete-orphan")
    topics = db.relationship("UserTopic", back_populates="user", cascade="all, delete-orphan")
    digest_times = db.relationship("UserDigestTime", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
```

---

## 3. Wire Up Flask-Login — `app/__init__.py`

Add to imports and factory:

```python
from flask_login import LoginManager

login_manager = LoginManager()

def create_app(...):
    ...
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access that page."
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id: str):
        from .models import User
        return db.session.get(User, int(user_id))

    # register blueprints
    from .auth import auth_bp
    app.register_blueprint(auth_bp)
    # ... existing blueprints ...
```

Also add a migration for the new column in `_run_migrations`:

```python
def _migrate_add_password_hash(app, db):
    """Add password_hash column to users if missing."""
    with app.app_context():
        try:
            db.session.execute(db.text("SELECT password_hash FROM users LIMIT 1"))
        except Exception:
            db.session.rollback()
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"
            ))
            db.session.commit()
            log.info("migration: added users.password_hash")
```

Call it inside `_run_migrations`.

---

## 4. New Auth Blueprint — `app/auth.py`

Create this file:

```python
"""Email/password login and logout."""
from __future__ import annotations

import re
import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app import limiter
from .models import User, db

log = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LEN = 8


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 30 per hour")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.feed"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password are required.", "error")
            return render_template("login.html"), 400

        user = db.session.query(User).filter(
            db.func.lower(User.email) == email
        ).first()

        if user is None or not user.check_password(password):
            # Constant-time-ish: always check even if user is None to avoid timing attacks
            flash("Invalid email or password.", "error")
            return render_template("login.html"), 401

        login_user(user, remember="remember_me" in request.form)
        log.info("login: user_id=%s", user.id)

        next_url = request.args.get("next", "")
        # Safety: only follow relative paths to prevent open redirect
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect(url_for("preferences.preferences"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    log.info("logout: user_id=%s", current_user.id)
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("main.feed"))
```

---

## 5. Update Subscribe — `app/subscriptions.py`

The subscribe form now collects a password and logs the user in on success.

Add password validation constants at the top:

```python
_MIN_PASSWORD_LEN = 8
```

In the `subscribe` POST handler, after creating the user, add:

```python
# Password
password = request.form.get("password", "")
confirm  = request.form.get("confirm_password", "")

if len(password) < _MIN_PASSWORD_LEN:
    flash(f"Password must be at least {_MIN_PASSWORD_LEN} characters.", "error")
    return render_template("subscribe.html", ...), 400

if password != confirm:
    flash("Passwords don't match.", "error")
    return render_template("subscribe.html", ...), 400

user.set_password(password)
```

After `db.session.commit()`, log the user in:

```python
from flask_login import login_user
login_user(user)
```

For returning subscribers (email already exists), prompt them to use login instead:

```python
existing = db.session.query(User).filter(
    db.func.lower(User.email) == email
).first()
if existing:
    flash("You're already subscribed. Log in to update your preferences.", "info")
    return redirect(url_for("auth.login"))
```

---

## 6. Update Preferences — `app/preferences.py`

Replace the email re-entry pattern with `@login_required` and `current_user`.

The preferences route simplifies significantly:

```python
from flask_login import current_user, login_required

@preferences_bp.route("/preferences", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute; 60 per hour")
def preferences():
    user = current_user   # no more email lookup

    if request.method == "GET":
        return _render_editor(user)

    # action is always "save" now (no more "load" step)
    try:
        # ... same save logic as before, using `user` directly ...
        flash("Your preferences have been saved.", "success")
        return _render_editor(user)
    except Exception as exc:
        log.error("preferences save failed: %s", exc)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return _render_editor(user), 500
```

Remove the `_find_user` function and the `action=load` / email form flow entirely. The GET now immediately shows the editor.

Update `_render_editor` to not need `user` passed — it uses `current_user` — or keep it accepting a user arg (either works).

---

## 7. New Template — `app/templates/login.html`

```html
{% extends "base.html" %}
{% block title %}Log in — AI Brief{% endblock %}

{% block content %}
<div class="max-w-sm mx-auto">
  <p class="text-xs font-semibold uppercase tracking-widest text-indigo-500 dark:text-indigo-400 mb-2">
    Welcome back
  </p>
  <h1 class="font-display text-3xl font-bold tracking-tight mb-8">Log in</h1>

  <form method="POST" action="{{ url_for('auth.login') }}{% if request.args.get('next') %}?next={{ request.args.get('next') | urlencode }}{% endif %}"
        class="space-y-4 rounded-2xl border border-zinc-200/80 dark:border-zinc-800
               bg-white/80 dark:bg-zinc-900/60 backdrop-blur p-6 sm:p-8
               shadow-xl shadow-zinc-900/5">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

    <div>
      <label for="email" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
        Email
      </label>
      <input type="email" id="email" name="email" required autocomplete="email"
             class="w-full rounded-xl border border-zinc-300 dark:border-zinc-700
                    bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-sm
                    text-zinc-900 dark:text-zinc-100 placeholder-zinc-400
                    focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500
                    transition">
    </div>

    <div>
      <label for="password" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
        Password
      </label>
      <input type="password" id="password" name="password" required autocomplete="current-password"
             class="w-full rounded-xl border border-zinc-300 dark:border-zinc-700
                    bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-sm
                    text-zinc-900 dark:text-zinc-100 placeholder-zinc-400
                    focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500
                    transition">
    </div>

    <label class="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400 cursor-pointer select-none">
      <input type="checkbox" name="remember_me"
             class="rounded border-zinc-300 dark:border-zinc-700 text-indigo-600 focus:ring-indigo-500">
      Keep me logged in
    </label>

    <button type="submit"
            class="w-full bg-gradient-to-r from-indigo-600 to-violet-600
                   hover:from-indigo-500 hover:to-violet-500 text-white font-semibold
                   py-3 px-4 rounded-xl text-sm shadow-lg shadow-indigo-600/25
                   transition-all active:scale-[0.98]">
      Log in
    </button>

    <p class="text-xs text-center text-zinc-500 dark:text-zinc-400">
      Don't have an account?
      <a href="{{ url_for('subscriptions.subscribe') }}"
         class="text-indigo-600 dark:text-indigo-400 font-medium hover:underline">
        Subscribe
      </a>
    </p>
  </form>
</div>
{% endblock %}
```

---

## 8. Update Subscribe Template — `app/templates/subscribe.html`

Add password fields after the email field:

```html
<!-- Password -->
<div>
  <label for="password" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
    Password
  </label>
  <input type="password" id="password" name="password" required
         minlength="8" autocomplete="new-password"
         placeholder="At least 8 characters"
         class="w-full rounded-xl border border-zinc-300 dark:border-zinc-700
                bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-sm
                text-zinc-900 dark:text-zinc-100 placeholder-zinc-400
                focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500
                transition">
</div>

<div>
  <label for="confirm_password" class="block text-sm font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
    Confirm password
  </label>
  <input type="password" id="confirm_password" name="confirm_password" required
         minlength="8" autocomplete="new-password"
         class="w-full rounded-xl border border-zinc-300 dark:border-zinc-700
                bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-sm
                text-zinc-900 dark:text-zinc-100 placeholder-zinc-400
                focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500
                transition">
</div>
```

Also update the submit button label to "Create account" and add below it:

```html
<p class="text-xs text-center text-zinc-500 dark:text-zinc-400">
  Already subscribed?
  <a href="{{ url_for('auth.login') }}"
     class="text-indigo-600 dark:text-indigo-400 font-medium hover:underline">Log in</a>
</p>
```

---

## 9. Update Base Template — `app/templates/base.html`

Add login/logout links to the nav. In the header, add:

```html
{% from 'flask_login' import current_user %}  {# this is Python, not Jinja — use the context variable directly #}

<nav class="... existing nav ...">
  {% if current_user.is_authenticated %}
    <a href="{{ url_for('preferences.preferences') }}"
       class="text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100">
      Preferences
    </a>
    <a href="{{ url_for('auth.logout') }}"
       class="text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100">
      Log out
    </a>
  {% else %}
    <a href="{{ url_for('auth.login') }}"
       class="text-sm text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100">
      Log in
    </a>
    <a href="{{ url_for('subscriptions.subscribe') }}"
       class="text-sm font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">
      Subscribe
    </a>
  {% endif %}
</nav>
```

Note: `current_user` is available in Jinja templates automatically once Flask-Login is initialized — no import needed in the template.

---

## 10. Update Preferences Template — `app/templates/preferences.html`

Remove the email-entry form (the `editing=False` state). The page now always shows the editor since the route requires login. Remove the `GET` email form and the `action=load` POST entirely.

---

## Files to Touch

| File | Change |
|---|---|
| `requirements.txt` | Add `flask-login` |
| `app/models.py` | Add `UserMixin`, `password_hash`, `set_password()`, `check_password()` |
| `app/__init__.py` | Init `LoginManager`, register `auth_bp`, add password_hash migration |
| `app/auth.py` | New file — login/logout routes |
| `app/subscriptions.py` | Add password fields + validation; `login_user()` after subscribe |
| `app/preferences.py` | Replace email re-entry with `@login_required` + `current_user` |
| `app/templates/login.html` | New file |
| `app/templates/subscribe.html` | Add password + confirm_password fields |
| `app/templates/preferences.html` | Remove email-entry state; always show editor |
| `app/templates/base.html` | Add login/logout/preferences nav links |

## Notes

- **Existing subscribers without a password** get redirected to the subscribe page if they try to log in. Alternatively, Cursor can add a "reset password via email" flow — but that requires email-sending infrastructure already in place if desired later.
- **The unsubscribe route stays public** — it uses a token from the email link, no login needed.
- **The feed stays public** — no login required to browse.
- **CSRF** is already handled globally via Flask-WTF; just add `csrf_token()` to the new login form.
- **Rate limiting** is already on the subscribe route; apply `@limiter.limit("10 per minute; 30 per hour")` to `/login`.
- **`remember_me`** uses Flask-Login's default 365-day cookie — acceptable for this use case.
