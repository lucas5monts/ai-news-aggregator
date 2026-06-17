# Feature: Pivot to General News Aggregator with AI-Powered Personalization

## What We're Building

Right now this app is a hardcoded AI-industry news digest. We're pivoting it to a **general news aggregator** where an LLM personalizes the feed to each user's stated interests. Users say what they care about ("F1 racing, climate policy, startups, NBA"), and the AI filters and ranks stories from a broad news source pool to match.

The core loop changes from:
> fetch AI RSS feeds → keyword filter → rank → deliver

To:
> fetch ALL news RSS feeds → LLM scores each story against user interests → rank by score + recency → deliver personalized feed

---

## What Stays the Same

- Flask + SQLAlchemy + APScheduler architecture
- The pipeline structure (`fetch → normalize → filter → rank → dedupe → cap`)
- Email delivery via Gmail SMTP
- CSRF, rate limiting, security headers added in the last session
- The web UI layout and component structure (feed, preview, subscribe pages)
- `Story` dataclass, `RawEntry` dataclass
- All existing tests — they should still pass after refactor

---

## Change 1: Expand RSS Sources (`config/sources.yaml`)

Replace the AI-only source list with a broad general news source set. Keep AI as one category among many. Suggested new categories and sources to add:

**world:** Reuters World, AP News, BBC World, Al Jazeera English
**us:** NPR News, PBS NewsHour, The Hill, Axios
**tech:** TechCrunch (keep), Ars Technica, The Verge, Wired (keep)
**ai:** OpenAI Blog (keep), Hugging Face (keep), Google DeepMind (keep), MIT Tech Review (keep)
**business:** Bloomberg Technology RSS, Financial Times Tech, Fortune
**science:** Nature News, New Scientist, Science Daily
**politics:** Politico, The Atlantic, FiveThirtyEight
**sports:** ESPN Top Headlines, BBC Sport

Add a `category` field to each source entry if not already present. This `category` maps to the story's `source_category` field.

Keep `weight` per source. Remove the `relevance_keywords` block from `config/settings.yaml` — it will be replaced by per-user interest topics.

---

## Change 2: User Interest Topics — Data Model

### New model: `UserTopic`

Add to `app/models.py`:

```python
class UserTopic(db.Model):
    __tablename__ = "user_topics"
    __allow_unmapped__ = True

    user_id   = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    topic     = db.Column(db.String(128), primary_key=True)  # e.g. "F1 racing"
    created_at = db.Column(db.DateTime(timezone=True), default=_now_utc, nullable=False)

    user = db.relationship("User", back_populates="topics")
```

Update `User` model to add: `topics = db.relationship("UserTopic", back_populates="user", cascade="all, delete-orphan")`

### Update `UserSettings`

Add a `max_categories` field (optional — can default to showing all categories) and remove any AI-specific defaults.

### Migration

Add a migration in `_run_migrations()` to `CREATE TABLE IF NOT EXISTS user_topics (...)` for existing installs. Use `db.create_all()` to handle fresh installs.

---

## Change 3: LLM-Powered Relevance Scoring (`core/relevance.py`)

Create a new file `core/relevance.py`. This replaces the keyword-based `filter_relevant()` for personalized (per-user) runs. The keyword filter can remain as a fallback for the public/global feed.

### Design

```python
"""Score stories against a user's interest topics using an LLM."""

def score_stories_for_user(
    stories: list[Story],
    user_topics: list[str],
    *,
    model: str = "claude-haiku-4-5-20251001",  # fast + cheap for bulk scoring
) -> list[Story]:
    """
    Send all story titles+summaries to the LLM in a single prompt.
    The LLM returns a relevance score (0.0–1.0) for each story given the user's topics.
    Stories with score < RELEVANCE_THRESHOLD are dropped.
    Score is folded into story.score (multiplied with recency*weight score).
    Returns filtered, re-scored list.
    """
```

**Prompt design (send to LLM):**
- System: "You are a news relevance engine. Given a user's interest topics and a list of news stories, score each story 0.0-1.0 for how relevant it is to the user's interests. Return ONLY a JSON array of scores in the same order as the stories."
- User: `{"topics": ["F1 racing", "climate policy"], "stories": [{"id": "abc", "title": "...", "summary": "..."}, ...]}`

**Implementation notes:**
- Use the Anthropic Python SDK (`anthropic` package — add to `requirements.txt`)
- Read `ANTHROPIC_API_KEY` from environment (add to `.env.example`)
- If `user_topics` is empty, skip LLM scoring and return all stories (no filter)
- If `ANTHROPIC_API_KEY` is missing, log a warning and fall back to keyword filter or no filter
- Cap at ~50 stories sent per LLM call to control token usage
- Cache LLM scores in memory keyed by `(frozenset(topics), story_id)` with a 1-hour TTL to avoid re-scoring identical stories for different users with the same interests
- `RELEVANCE_THRESHOLD = 0.4` — drop stories below this score
- Fold LLM score into final `story.score`: `story.score = story.score * llm_score`

---

## Change 4: Pipeline — Personalized vs. Global Runs (`core/pipeline.py`)

The existing `filter_relevant(stories, keywords, window_hours)` stays for the global/public feed (where there's no user context). Add a new pipeline path for per-user digest runs.

Update `app/scheduler.py`'s `_send_digest_for_user()` to:
1. Fetch user's topics from DB
2. Run `pipeline.normalize` + `pipeline.rank` as before
3. Replace `pipeline.filter_relevant(stories, keywords, window_hours)` with `relevance.score_stories_for_user(stories, user_topics)` when topics are set
4. Continue with dedupe, cap, deliver

The public `/feed` route keeps using keyword filter (or no filter if keywords are removed from settings.yaml — show everything ranked by recency+weight).

---

## Change 5: Subscribe Flow — Add Topic Selection (`app/subscriptions.py` + template)

### Update `/subscribe` POST handler

After saving email + schedule preferences, accept a `topics` form field — a comma-separated or newline-separated list of interest phrases entered by the user. Parse, clean, and save to `user_topics` table (max 20 topics, each max 80 chars).

### Update `subscribe.html`

Add a topic input section to the form:

```
Your interests (optional)
[textarea placeholder: "e.g. climate change, NBA basketball, AI startups, geopolitics, Formula 1"]
We'll use these to filter your digest. Leave blank for top general news.
```

Below the textarea, show a row of quick-add chips for common topic groups:
- 🌍 World News  🤖 AI & Tech  💼 Business  🔬 Science  🏆 Sports  🗳️ Politics

Clicking a chip appends it to the textarea.

---

## Change 6: User Preferences Page (new route `/preferences`)

Add a new route to `app/routes.py` (or a new blueprint `app/preferences.py`):

- `GET /preferences` — show current topics, schedule settings, source toggles
- `POST /preferences` — update topics and settings

This is a minimal form — no login, identify user by email (they re-enter their email to edit prefs, similar to how many newsletter tools work). Or use a signed token in the digest email footer ("Update your preferences →") that contains the user_id. Start with the email re-entry approach for simplicity.

Add a link to the nav: "Preferences" alongside Feed / Preview / Subscribe.

---

## Change 7: Web Feed — Show Topic Context

Update `app/routes.py`'s `/feed` route:

- The global feed shows all news ranked by recency+weight, no LLM filter (it's public)
- Add a sidebar widget on the feed page: "Personalize your feed" → links to /subscribe or /preferences
- Show a category filter bar above stories (use the new broader category list from sources.yaml)
- The existing `/preview` route can stay as-is for now

---

## Change 8: Config Cleanup (`config/settings.yaml`)

Remove `relevance_keywords` block — it's replaced by per-user topics. Keep:
- `max_stories`
- `default_time_window_hours`
- `digest.max_summary_chars`
- `digest.category_order` — expand to include all new categories

Add new settings:
```yaml
llm:
  relevance_threshold: 0.4
  max_stories_to_score: 50   # cap sent to LLM per call
  fallback_to_all: true      # if LLM fails, show all stories rather than nothing
```

---

## Change 9: Environment Variables (`.env.example`)

Add:
```
# Anthropic API key — used to personalize digests based on user topics
# Get one at https://console.anthropic.com
ANTHROPIC_API_KEY=your-key-here
```

---

## New File Summary

| File | Action |
|---|---|
| `config/sources.yaml` | Replace AI-only sources with general news sources across 8 categories |
| `config/settings.yaml` | Remove `relevance_keywords`, add `llm:` config block |
| `core/relevance.py` | New — LLM scoring via Anthropic SDK |
| `app/models.py` | Add `UserTopic` model, update `User` relationships |
| `app/__init__.py` | Add migration for `user_topics` table |
| `app/subscriptions.py` | Parse + save topics from form |
| `app/routes.py` | Add `/preferences` route; update `/feed` category filter |
| `app/scheduler.py` | Use `relevance.score_stories_for_user()` in per-user digest job |
| `app/templates/subscribe.html` | Add topic textarea + chip quick-adds |
| `app/templates/preferences.html` | New page |
| `app/templates/base.html` | Add Preferences to nav |
| `app/templates/feed.html` | Add category filter bar |
| `requirements.txt` | Add `anthropic` |
| `.env.example` | Add `ANTHROPIC_API_KEY` |

---

## Constraints & Decisions

- **No vector DB / embeddings** — LLM prompt-based scoring only. Simpler to deploy, good enough for <100 stories per call.
- **No user auth** — users identify by email for preferences. Keep it frictionless.
- **Backward compat** — users with no topics set get the full general feed (no LLM filter). The app works without an API key, just without personalization.
- **Tests** — mock the LLM call in tests (`ANTHROPIC_API_KEY` absent → fallback path). Existing 45 tests must still pass.
- **Rename** — consider renaming the app from "AI News" to something like "Brief" or "Daily Brief" in the UI, but don't change file/module names yet — that's a separate cosmetic pass.
