# Security Fixes — Auth Layer Round 2

Two small fixes across `app/subscriptions.py` and `app/auth.py`.

---

## Fix 1: Enforce password maximum length

**File: `app/subscriptions.py`**

`generate_password_hash` (PBKDF2) is intentionally CPU-intensive. No upper bound on password length means a megabyte-sized POST body runs a full hash computation on every request — a cheap DoS vector.

Add a max-length constant alongside the existing min:

```python
_MIN_PASSWORD_LEN = 8
_MAX_PASSWORD_LEN = 128
```

Add the check immediately after the min-length check (around line 180):

```python
if len(password) < _MIN_PASSWORD_LEN:
    flash(f"Password must be at least {_MIN_PASSWORD_LEN} characters.", "error")
    return render_template(
        "subscribe.html",
        initial_times=parse_times(request.form.getlist("custom_times")),
    ), 400

if len(password) > _MAX_PASSWORD_LEN:
    flash(f"Password must be {_MAX_PASSWORD_LEN} characters or fewer.", "error")
    return render_template(
        "subscribe.html",
        initial_times=parse_times(request.form.getlist("custom_times")),
    ), 400
```

---

## Fix 2: Don't confirm whether an email is registered on subscribe

**File: `app/subscriptions.py`**

The current response when a duplicate email is submitted:

```python
flash("You're already subscribed. Log in to update your preferences.", "info")
return redirect(url_for("auth.login"))
```

This tells an attacker whether any given email is registered. Replace with a response that doesn't confirm or deny:

```python
# Don't reveal whether the email is registered.
flash(
    "If that email is already subscribed, log in to manage your preferences.",
    "info",
)
return redirect(url_for("auth.login"))
```

---

## Fix 3 (cleanup): Remove unused `_EMAIL_RE` from auth.py

**File: `app/auth.py`**

`_EMAIL_RE` is defined on line 18 but never referenced. Remove the import and the constant to avoid confusion:

```python
# Remove these two lines:
import re
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
```

Only remove `import re` if it's not used elsewhere in the file. If it is, just remove the `_EMAIL_RE` line.

---

## Files to touch

| File | Change |
|---|---|
| `app/subscriptions.py` | Add `_MAX_PASSWORD_LEN = 128` check; soften duplicate-email flash message |
| `app/auth.py` | Remove unused `_EMAIL_RE` and `import re` if unused |
