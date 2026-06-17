# Feature: Enhanced Subscribe Form — Topic Picker + Custom Send Time

Two improvements to the subscribe page:
1. Replace the topics textarea with an interactive chip-based topic picker
2. Replace the fixed 6 AM / 8 PM time slots with user-defined time inputs

Both changes touch the form UI, the POST handler, the data model, a migration, and the scheduler.

---

## Part 1: Topic Picker UI

### What to build

Replace the plain textarea for topics with a visual chip/tag selector. Users click pre-built topic chips to toggle them, and can also type a custom topic and press Enter to add it. Selected topics appear as removable tags. A hidden input carries the final comma-separated list on submit.

### Pre-built topic chips

Group them visually. Suggested chip labels (these become the topic strings stored in `user_topics`):

**News:**
World News · US News · Politics · Business · Science · Health · Climate · Technology

**Sports:**
NBA · NFL · Soccer · Formula 1 · Tennis · MLB

**Culture:**
AI & Machine Learning · Space · Finance · Crypto · Entertainment · Food

### HTML/JS approach (no external libraries, pure vanilla)

The form section for topics in `subscribe.html` should look like this functionally:

```
[Your interests]
Click topics to add them, or type your own below.

[World News ×] [NBA ×] [Formula 1 ×]          ← selected tags row

[ Type a topic and press Enter... ]             ← custom input

─── Quick picks ─────────────────────────────
[ World News ] [ US News ] [ Politics ] ...     ← pre-built chips (click to toggle)
[ NBA ] [ NFL ] [ Soccer ] [ Formula 1 ] ...
[ AI & ML ] [ Space ] [ Finance ] [ Crypto ] ...
─────────────────────────────────────────────

<input type="hidden" name="topics" value="World News,NBA,Formula 1">
```

**JS behavior:**
- Clicking a pre-built chip: if not already selected → add to tags row + update hidden input. If already selected → remove it.
- Typing in custom input and pressing Enter: trim, validate length (≤80 chars), max 20 total, add as tag.
- Clicking `×` on a tag removes it and un-highlights the chip if it was a pre-built one.
- Hidden input `name="topics"` always reflects the current comma-separated list of selected topics.

Keep all JS inline in `subscribe.html` (no separate file needed).

### Backend — no change needed for Part 1

The topics POST handling from the pivot prompt already reads `request.form.get("topics")` and splits on commas. No backend change required — just the UI.

---

## Part 2: Custom Send Time

### Current behavior (to replace)

`UserSettings` has `morning_enabled` (bool, default 6 AM) and `evening_enabled` (bool, default 8 PM). The scheduler hardcodes those times in `is_users_morning` and `is_users_evening`.

### New behavior

Users pick a checkbox to enable a digest slot, then pick any time via a time input. Each enabled slot delivers once daily at that time in their timezone.

### Data model changes — `app/models.py`

Add two new columns to `UserSettings`:

```python
morning_time = db.Column(db.String(5), default="06:00", nullable=False)  # "HH:MM"
evening_time = db.Column(db.String(5), default="20:00", nullable=False)  # "HH:MM"
```

These store the time as a simple "HH:MM" 24-hour string. `morning_enabled` and `evening_enabled` booleans stay — they control whether that slot is active at all.

### Migration — `app/__init__.py`

Add a new migration function `_migrate_add_digest_times(db)` called from `_run_migrations()`:

```python
def _migrate_add_digest_times(db) -> None:
    """Add morning_time and evening_time columns to user_settings if missing."""
    from sqlalchemy import text
    try:
        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(user_settings)"))
            cols = [row[1] for row in result]
            if "morning_time" not in cols:
                conn.execute(text("ALTER TABLE user_settings ADD COLUMN morning_time TEXT NOT NULL DEFAULT '06:00'"))
            if "evening_time" not in cols:
                conn.execute(text("ALTER TABLE user_settings ADD COLUMN evening_time TEXT NOT NULL DEFAULT '20:00'"))
            conn.commit()
    except Exception as exc:
        log.debug("_migrate_add_digest_times: %s (skipping)", exc)
```

### Scheduler changes — `app/scheduler.py`

Update `is_users_morning` and `is_users_evening` to accept an optional `time_str` param instead of hardcoding the hour/minute:

```python
def is_users_morning(user_tz: str, time_str: str = "06:00", now_utc=None) -> bool:
    hour, minute = _parse_time_str(time_str)
    return _is_hour_minute(user_tz, hour=hour, minute=minute, now_utc=now_utc)

def is_users_evening(user_tz: str, time_str: str = "20:00", now_utc=None) -> bool:
    hour, minute = _parse_time_str(time_str)
    return _is_hour_minute(user_tz, hour=hour, minute=minute, now_utc=now_utc)

def _parse_time_str(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' → (hour, minute). Falls back to (6, 0) on bad input."""
    try:
        h, m = time_str.split(":")
        return int(h), int(m)
    except Exception:
        return 6, 0
```

Update `_digest_job` in `scheduler.py` to pass each user's stored time when calling the check function:

```python
# In _digest_job, where it calls check_fn:
time_str = settings.morning_time if edition == "morning" else settings.evening_time
if not check_fn(settings.timezone, time_str=time_str, now_utc=now_utc):
    continue
```

### Subscribe POST handler — `app/subscriptions.py`

Read the new time fields from the form and validate them before saving:

```python
def _parse_form_time(raw: str, fallback: str) -> str:
    """Validate 'HH:MM' format and return it, or return fallback."""
    import re
    raw = raw.strip()
    if re.match(r"^([01]\d|2[0-3]):[0-5]\d$", raw):
        return raw
    return fallback

morning_time = _parse_form_time(request.form.get("morning_time", ""), "06:00")
evening_time = _parse_form_time(request.form.get("evening_time", ""), "20:00")

# Then in subscribe_email() or directly after getting settings:
settings.morning_time = morning_time
settings.evening_time = evening_time
```

Update `subscribe_email()` signature to accept `morning_time` and `evening_time` params and save them.

### Form UI — `subscribe.html`

Replace the current fixed-time checkboxes with conditional time inputs. Each edition has a checkbox to enable it + a time picker that appears when the checkbox is checked:

```html
<div class="space-y-3">
  <p class="text-xs font-semibold uppercase tracking-wider text-zinc-500">Delivery schedule</p>

  <!-- Morning slot -->
  <div class="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3">
    <label class="flex items-center gap-3 cursor-pointer">
      <input type="checkbox" name="morning_enabled" id="morning_enabled" checked
             class="h-4 w-4 rounded text-indigo-600 focus:ring-indigo-500">
      <div class="flex-1">
        <span class="text-sm font-medium block">Morning digest</span>
        <span class="text-xs text-zinc-500">Delivered once daily in your timezone</span>
      </div>
      <input type="time" name="morning_time" id="morning_time" value="06:00"
             class="text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 px-2 py-1
                    bg-zinc-50 dark:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-indigo-500
                    disabled:opacity-40 disabled:cursor-not-allowed">
    </label>
  </div>

  <!-- Evening slot -->
  <div class="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3">
    <label class="flex items-center gap-3 cursor-pointer">
      <input type="checkbox" name="evening_enabled" id="evening_enabled"
             class="h-4 w-4 rounded text-indigo-600 focus:ring-indigo-500">
      <div class="flex-1">
        <span class="text-sm font-medium block">Evening digest</span>
        <span class="text-xs text-zinc-500">Delivered once daily in your timezone</span>
      </div>
      <input type="time" name="evening_time" id="evening_time" value="20:00"
             class="text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 px-2 py-1
                    bg-zinc-50 dark:bg-zinc-800 focus:outline-none focus:ring-2 focus:ring-indigo-500
                    disabled:opacity-40 disabled:cursor-not-allowed">
    </label>
  </div>
</div>
```

Add a small inline JS block at the bottom of the form that disables the time input when its checkbox is unchecked:

```javascript
['morning', 'evening'].forEach(function(slot) {
  var cb = document.getElementById(slot + '_enabled');
  var ti = document.getElementById(slot + '_time');
  function sync() { ti.disabled = !cb.checked; }
  sync();
  cb.addEventListener('change', sync);
});
```

---

## Files to Touch

| File | Change |
|---|---|
| `app/models.py` | Add `morning_time` and `evening_time` columns to `UserSettings` |
| `app/__init__.py` | Add `_migrate_add_digest_times()` migration |
| `app/scheduler.py` | Update `is_users_morning/evening` to accept `time_str`; pass user's stored time in `_digest_job` |
| `app/subscriptions.py` | Read + validate `morning_time` / `evening_time` from form; save to settings; update `subscribe_email()` signature |
| `app/templates/subscribe.html` | Replace static checkboxes with checkbox+time-input pairs; add topic chip picker with inline JS |

---

## Tests to update

- `tests/test_scheduler.py` — `is_users_morning` / `is_users_evening` now take a `time_str` param; update any calls that relied on the old signature
- `tests/test_subscriptions.py` — add cases for `morning_time` / `evening_time` POST params, and for invalid time strings falling back to defaults
- No changes needed to the other 40+ tests
