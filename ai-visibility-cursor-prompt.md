# Feature: Surface the AI — Make Personalization Visible

Right now the LLM scores every story against the user's interests, but the UI looks like a plain RSS reader. These changes make the AI's work visible at every level — per-story, per-feed, and in motion.

---

## 1. Per-Card Topic Match Tag

**Files:** `core/pipeline.py` (Story model), `core/relevance.py`, `app/templates/_macros.html`

Each story card should show which of the user's interest topics caused it to be included.

### Data model change — add `matched_topic` to Story

In `core/pipeline.py`, add a field to the `Story` dataclass:

```python
@dataclass
class Story:
    ...
    matched_topic: str | None = None   # the user interest that best matched this story
    llm_score: float | None = None     # raw LLM relevance score (0.0–1.0)
```

### Populate it in `core/relevance.py`

After scoring, for each kept story, store the topic that contributed the highest score. Since one LLM call scores all stories against all topics at once, add a second call or infer it: do a simple case-insensitive substring check between `story.title + story.summary` and each topic, pick the one with the best match. Fall back to the first topic in the list if no substring match.

```python
def _best_matching_topic(story: "Story", topics: list[str]) -> str | None:
    """Return the topic most likely responsible for this story being included."""
    haystack = f"{story.title} {story.summary}".lower()
    for topic in topics:
        if topic.lower() in haystack:
            return topic
    return topics[0] if topics else None
```

Call it after keeping a story and set `story.matched_topic = _best_matching_topic(story, topics)` and `story.llm_score = llm_score`.

### Show it on the card — `app/templates/_macros.html`

In `story_card`, `hero_card`, and `story_list_item`, add a topic match chip just below the category badge, only when `story.matched_topic` is set:

```html
{% if story.matched_topic %}
<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold
             bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 ring-1 ring-inset ring-indigo-500/20">
  <i data-lucide="sparkles" class="w-2.5 h-2.5"></i>
  {{ story.matched_topic }}
</span>
{% endif %}
```

For `hero_card`, also show the LLM score as a subtle confidence bar if `story.llm_score` is set:

```html
{% if story.llm_score %}
<div class="flex items-center gap-2 mt-3">
  <span class="text-[10px] font-medium text-zinc-400 uppercase tracking-wider">Relevance</span>
  <div class="flex-1 h-1 rounded-full bg-zinc-200 dark:bg-zinc-700 max-w-[80px]">
    <div class="h-1 rounded-full bg-indigo-500"
         style="width: {{ (story.llm_score * 100) | int }}%"></div>
  </div>
  <span class="text-[10px] text-zinc-400">{{ (story.llm_score * 100) | int }}%</span>
</div>
{% endif %}
```

---

## 2. Personalized Feed Header

**File:** `app/templates/feed.html`, `app/routes.py`

When a user has topics set (detectable by whether any stories have `matched_topic`), show a banner above the feed summarizing what the AI did.

### Route change — `app/routes.py`

Pass metadata from the pipeline to the template:

```python
# In _run_pipeline_global() return value, also return ai_metadata dict:
ai_metadata = {
    "personalized": any(s.matched_topic for s in stories),
    "total_scored": total_scanned,
    "topics_active": list({s.matched_topic for s in stories if s.matched_topic}),
    "kept": len(stories),
}
```

Pass it to the template:
```python
return render_template("feed.html", stories=stories, total_scanned=total_scanned,
                       categories=_load_categories(), selected_category=category,
                       ai_meta=ai_metadata)
```

### Template change — `app/templates/feed.html`

Replace the current static subtitle with a dynamic AI summary block:

```html
{% if ai_meta and ai_meta.personalized %}
<!-- Personalized feed header -->
<div class="flex items-start gap-3 px-4 py-3 rounded-2xl
            bg-indigo-500/5 dark:bg-indigo-500/10
            border border-indigo-200/60 dark:border-indigo-500/20 mb-8">
  <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600
              flex items-center justify-center shrink-0 shadow-sm shadow-indigo-500/20">
    <i data-lucide="sparkles" class="w-4 h-4 text-white"></i>
  </div>
  <div class="min-w-0">
    <p class="text-sm font-semibold text-indigo-700 dark:text-indigo-300">
      Personalized by Claude
    </p>
    <p class="text-xs text-indigo-600/70 dark:text-indigo-400/70 mt-0.5">
      Scored {{ ai_meta.total_scored }} stories against your interests
      and selected {{ ai_meta.kept }} for you
      {% if ai_meta.topics_active %}
        — matching
        {% for t in ai_meta.topics_active[:3] %}
          <span class="font-medium">{{ t }}</span>{% if not loop.last %}, {% endif %}
        {% endfor %}
        {% if ai_meta.topics_active | length > 3 %}and {{ ai_meta.topics_active | length - 3 }} more{% endif %}
      {% endif %}.
    </p>
  </div>
</div>

{% else %}
<!-- No-topics nudge (public feed) -->
<div class="flex items-center justify-between gap-4 px-4 py-3 rounded-2xl
            bg-zinc-50 dark:bg-zinc-900/60
            border border-zinc-200/60 dark:border-zinc-800 mb-8">
  <div class="flex items-center gap-3">
    <div class="w-8 h-8 rounded-lg bg-zinc-200 dark:bg-zinc-800 flex items-center justify-center">
      <i data-lucide="sparkles" class="w-4 h-4 text-zinc-500 dark:text-zinc-400"></i>
    </div>
    <p class="text-sm text-zinc-600 dark:text-zinc-400">
      This is the general feed.
      <span class="font-medium text-zinc-800 dark:text-zinc-200">Add your interests</span>
      and Claude will personalize it for you.
    </p>
  </div>
  <a href="{{ url_for('subscriptions.subscribe') }}"
     class="shrink-0 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">
    Set topics →
  </a>
</div>
{% endif %}
```

---

## 3. Animated AI Refresh States

**File:** `app/templates/feed.html`

The "Refresh feed" button currently just shows a spinning icon. Replace it with a multi-step status message that communicates what the AI is doing.

Add a `<div id="refresh-status">` that updates via HTMX events:

```html
<div id="refresh-status" class="hidden text-xs text-indigo-500 dark:text-indigo-400 font-medium
                                 flex items-center gap-2 animate-pulse">
  <i data-lucide="sparkles" class="w-3.5 h-3.5"></i>
  <span id="refresh-status-text">Reading sources…</span>
</div>
```

Add JS that cycles through messages during the HTMX request:

```javascript
var refreshMessages = [
  'Reading sources…',
  'Fetching latest stories…',
  'Scoring against your interests…',
  'Ranking and deduping…',
  'Almost done…',
];
var refreshStatusEl = document.getElementById('refresh-status');
var refreshStatusText = document.getElementById('refresh-status-text');
var refreshMsgTimer = null;
var refreshMsgIndex = 0;

document.body.addEventListener('htmx:sendingRequest', function (e) {
  if (!e.detail.requestConfig.path.includes('/feed/refresh')) return;
  refreshMsgIndex = 0;
  refreshStatusEl.classList.remove('hidden');
  refreshStatusText.textContent = refreshMessages[0];
  refreshMsgTimer = setInterval(function () {
    refreshMsgIndex = (refreshMsgIndex + 1) % refreshMessages.length;
    refreshStatusText.textContent = refreshMessages[refreshMsgIndex];
  }, 1800);
});

document.body.addEventListener('htmx:afterSwap', function () {
  clearInterval(refreshMsgTimer);
  refreshStatusEl.classList.add('hidden');
});
```

Place `<div id="refresh-status">` next to the refresh button in the header row.

---

## 4. Topic Activity Widget (Sidebar)

**File:** `app/templates/feed_items.html`

In the sidebar, replace or supplement the static "Sources" widget with a "Your interests today" widget that shows which of the user's topics had matching stories and how many.

This requires the stories passed to the template to have `matched_topic` set. Group by `matched_topic` and count:

```html
{% set matched_topics = {} %}
{% for s in stories %}
  {% if s.matched_topic %}
    {% if s.matched_topic not in matched_topics %}
      {% set _ = matched_topics.update({s.matched_topic: 0}) %}
    {% endif %}
    {% set _ = matched_topics.update({s.matched_topic: matched_topics[s.matched_topic] + 1}) %}
  {% endif %}
{% endfor %}

{% if matched_topics %}
<div class="rounded-3xl border border-zinc-200/80 dark:border-zinc-800 bg-white/60 dark:bg-zinc-900/40 p-6">
  <div class="flex items-center gap-2 mb-4">
    <i data-lucide="sparkles" class="w-3.5 h-3.5 text-indigo-500"></i>
    <h3 class="text-xs font-semibold uppercase tracking-widest text-zinc-500 dark:text-zinc-400">Your interests today</h3>
  </div>
  <ul class="space-y-2">
    {% for topic, count in matched_topics.items() | sort(attribute='1', reverse=True) %}
    <li class="flex items-center justify-between gap-3 py-1.5 text-sm
               border-b border-zinc-100 dark:border-zinc-800/60 last:border-0">
      <span class="flex items-center gap-2 text-zinc-700 dark:text-zinc-300 font-medium truncate">
        <span class="w-1.5 h-1.5 rounded-full bg-indigo-500 shrink-0"></span>
        {{ topic }}
      </span>
      <span class="text-xs font-semibold text-indigo-600 dark:text-indigo-400 shrink-0">
        {{ count }} {{ 'story' if count == 1 else 'stories' }}
      </span>
    </li>
    {% endfor %}
  </ul>
</div>
{% endif %}
```

---

## Files to Touch

| File | Change |
|---|---|
| `core/pipeline.py` | Add `matched_topic: str \| None` and `llm_score: float \| None` to `Story` dataclass |
| `core/relevance.py` | Add `_best_matching_topic()`; set `story.matched_topic` and `story.llm_score` on kept stories |
| `app/routes.py` | Build and pass `ai_meta` dict from pipeline to feed/feed_refresh templates |
| `app/templates/_macros.html` | Add topic chip and relevance bar to `story_card`, `hero_card`, `story_list_item` |
| `app/templates/feed.html` | Add personalized/public-feed header banner; add animated refresh status + JS |
| `app/templates/feed_items.html` | Add "Your interests today" sidebar widget |

## Notes

- Stories on the **public feed** (no user topics, no LLM call) will have `matched_topic = None` and `llm_score = None` — the chips simply don't render. No change to the public feed experience.
- The `_best_matching_topic()` function is a heuristic (substring match), not a second LLM call — it adds zero latency.
- The relevance bar on the hero card is purely cosmetic but gives a strong "AI did this" signal for the top story.
