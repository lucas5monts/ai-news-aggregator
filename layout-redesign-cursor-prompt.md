# Layout: 3-Column Magazine Grid (Above the Fold)

The current top section shows 1 giant hero + a text sidebar. The reference layout (AI News) shows 7 stories above the fold using a 3-column structure:

```
[ hero — portrait image + overlay text ] [ 2×2 card grid ] [ text headlines ]
     ~38% width                               ~40% width        ~22% width
```

The changes are entirely in `app/templates/feed_items.html` and `app/templates/_macros.html`. No Python changes needed.

---

## 1. New macro: `hero_card_portrait` — `app/templates/_macros.html`

The current `hero_card` is a landscape split (image left, text right). The reference layout uses a portrait/square card where the image fills the whole card and the title is overlaid at the bottom. Add a new macro for this:

```jinja
{# Portrait hero — image fills card, title overlaid at bottom. #}
{% macro hero_card_portrait(story) %}
  <article class="group h-full">
    <a href="{{ story.url | safe_url }}" target="_blank" rel="noopener noreferrer"
       class="relative flex flex-col h-full min-h-[420px] overflow-hidden rounded-3xl
              border border-zinc-200/80 dark:border-zinc-800 shadow-sm
              hover:shadow-2xl hover:shadow-indigo-500/10 transition-all duration-300">
      {# Full-bleed background image #}
      {% set thumb = (story.image_url | card_image) or (story.source_name | placeholder_image(story.source_category)) %}
      <img src="{{ thumb }}"
           alt=""
           loading="eager"
           referrerpolicy="no-referrer"
           data-fallback="{{ story.source_name | placeholder_image(story.source_category) }}"
           class="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
           onerror="if(this.src!==this.dataset.fallback){this.onerror=null;this.src=this.dataset.fallback;}">
      {# Dark gradient scrim so text is readable #}
      <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent pointer-events-none"></div>
      {# Text overlay at bottom #}
      <div class="relative mt-auto p-6">
        <div class="flex items-center gap-2 mb-3 flex-wrap">
          {{ category_badge(story.source_category) }}
          {{ topic_match_chip(story) }}
          <span class="text-xs text-white/70 ml-auto">{{ story.published_at | time_ago }}</span>
        </div>
        <h2 class="font-display font-bold leading-tight tracking-tight text-white
                   group-hover:text-indigo-300 transition-colors text-2xl sm:text-3xl">
          {{ story.title }}
        </h2>
        {% if story.summary %}
        <p class="text-sm text-white/75 leading-relaxed mt-2 line-clamp-2">
          {{ story.summary }}
        </p>
        {% endif %}
        <span class="inline-flex items-center gap-1.5 text-sm font-semibold text-indigo-300 mt-4">
          Read story
          <i data-lucide="arrow-right" class="w-4 h-4 group-hover:translate-x-0.5 transition-transform"></i>
        </span>
      </div>
    </a>
  </article>
{% endmacro %}
```

Keep the existing `hero_card` macro — it is still used elsewhere (e.g. the preview page).

---

## 2. Restructure the top section — `app/templates/feed_items.html`

Replace the current "Top story" section (lines 69–89) with a 3-column magazine grid:

**Remove this block:**
```jinja
{# Featured hero: large lead story + side rail of next headlines #}
{% if stories | length >= 1 %}
<section class="mb-12">
  <p class="text-xs font-semibold uppercase tracking-widest text-indigo-500 dark:text-indigo-400 mb-4">Top story</p>
  <div class="grid lg:grid-cols-3 2xl:grid-cols-4 gap-6 lg:gap-8 items-stretch">
    <div class="lg:col-span-2 2xl:col-span-3">
      {{ hero_card(stories[0]) }}
    </div>
    {% if stories | length >= 2 %}
    <aside class="lg:col-span-1 flex flex-col rounded-3xl border border-zinc-200/80 dark:border-zinc-800
                  bg-white/60 dark:bg-zinc-900/40 px-5 sm:px-6">
      <p class="text-xs font-semibold uppercase tracking-widest text-zinc-500 dark:text-zinc-400 pt-5 pb-1">Latest headlines</p>
      <div class="divide-y divide-zinc-200/80 dark:divide-zinc-800">
        {% for s in stories[1:5] %}
          {{ story_list_item(s) }}
        {% endfor %}
      </div>
    </aside>
    {% endif %}
  </div>
</section>
{% endif %}
```

**Replace with:**
```jinja
{% from "_macros.html" import hero_card_portrait %}

{% if stories | length >= 1 %}
<section class="mb-12">
  <div class="grid lg:grid-cols-[5fr_5fr_3fr] gap-5 lg:gap-6 items-stretch">

    {# Column 1: Portrait hero #}
    <div class="lg:col-span-1">
      {{ hero_card_portrait(stories[0]) }}
    </div>

    {# Column 2: 2×2 card grid (stories 1–4) #}
    {% if stories | length >= 2 %}
    <div class="lg:col-span-1 grid grid-cols-2 gap-4 content-start">
      {% for s in stories[1:5] %}
        {{ story_card(s) }}
      {% endfor %}
    </div>
    {% endif %}

    {# Column 3: Text headlines sidebar (stories 5–10) #}
    {% if stories | length >= 6 %}
    <aside class="lg:col-span-1 flex flex-col rounded-3xl border border-zinc-200/80 dark:border-zinc-800
                  bg-white/60 dark:bg-zinc-900/40 px-5 sm:px-6 self-start">
      <p class="text-xs font-semibold uppercase tracking-widest text-zinc-500 dark:text-zinc-400 pt-5 pb-1">
        Latest headlines
      </p>
      <div class="divide-y divide-zinc-200/80 dark:divide-zinc-800">
        {% for s in stories[5:11] %}
          {{ story_list_item(s) }}
        {% endfor %}
      </div>
    </aside>
    {% endif %}

  </div>
</section>
{% endif %}
```

---

## 3. Update the "rest" stories slice — `app/templates/feed_items.html`

The bottom category blocks currently start at `stories[5:]`. Since the new layout now uses stories 0–10 above the fold, update the slice:

**Change:**
```jinja
{% set rest = stories[5:] %}
```

**To:**
```jinja
{% set rest = stories[11:] %}
```

If `max_stories` is 15, this means stories 11–14 go into the category blocks below. If you want more content in the bottom section, consider increasing `max_stories` in `config/settings.yaml` from 15 to 20 or 25. This would give:
- Stories 0–10 → above-the-fold magazine grid (11 stories)
- Stories 11+ → category blocks below the fold

---

## 4. Make story cards in the 2×2 grid more compact

The existing `story_card` macro works well but uses `aspect-[16/11]` which can be tall in a 2-column grid. No macro change needed — the Tailwind grid handles sizing — but if the cards look too tall, change the aspect ratio inside `story_card` for small contexts:

The grid `grid-cols-2 gap-4` will naturally size the cards appropriately. If you want, add `text-sm` or `text-[13px]` to the title inside `story_card` when it's used in the grid, but this is optional cosmetic tuning.

---

## Summary of changes

| File | Change |
|---|---|
| `app/templates/_macros.html` | Add `hero_card_portrait` macro (keep existing `hero_card`) |
| `app/templates/feed_items.html` | Replace 2-col top section with 3-col grid; update `rest = stories[11:]` |
| `config/settings.yaml` *(optional)* | Increase `max_stories` from 15 to 20–25 for more content |

## Notes
- On mobile (< lg breakpoint), the 3 columns stack vertically: hero first, then 2×2 grid, then headlines. This is good UX.
- The `hero_card_portrait` uses `min-h-[420px]` so it stays tall on all screen sizes. Adjust this value if it feels too tall or too short on your monitor.
- The `[5fr_5fr_3fr]` column ratio gives roughly 38% | 38% | 23%, matching the reference site proportions.
