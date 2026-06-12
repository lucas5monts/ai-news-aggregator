# AI News Dashboard — UI Modernization

## Part 1 — The Plan

### What's dated right now

After reading every template (`base.html`, `login.html`, `feed.html`, `feed_items.html`, `settings.html`, `settings_form.html`, `preview.html`, `archive.html`):

- **Emoji icons everywhere** (📡 ⚙️ 👁 🗃 📰 ✉ ⟳ 📭) — these read as 2018 hobby-project. Modern apps use clean line icons (Lucide, Heroicons).
- **Generic Tailwind blue-600** with no custom palette. Looks like every Bootstrap admin template.
- **System default font** (`font-sans` = whatever the OS picks). Modern apps ship Inter/Geist/SF.
- **Inconsistent radii** — `rounded-md`, `rounded-lg`, `rounded-xl` mixed across components.
- **Card-on-gray-50** layout — classic 2020 admin-panel look (think early Notion/Linear). Modern apps are flatter, with subtle borders instead of separate background layers.
- **No dark mode** — table stakes for dev-adjacent tools in 2026.
- **Empty states are emoji + text** — no real illustration, no real polish.
- **Loading state is a spinner emoji (⟳)** that rotates — should be a skeleton or a proper spinner.
- **Sidebar uses pill-shaped active states** with emoji + text on a plain background — feels heavy.

### Design direction

Aim for a **Linear / Vercel / Raycast** aesthetic: tight, neutral, monochrome-with-one-accent, line icons, real typography, dark-mode-first feeling even in light mode.

**Tokens to standardize on:**

| Token | Value |
|---|---|
| Body font | Inter (via Google Fonts CDN, with `font-feature-settings: 'cv11', 'ss01'`) |
| Mono font | JetBrains Mono (for timestamps, source names, IDs) |
| Neutrals | Tailwind `zinc` palette (warmer than `gray`, less blue than `slate`) |
| Accent | `indigo-500` for primary actions, `emerald-500` for success/send |
| Radius | `rounded-lg` (8px) across the board — no more `rounded-xl` for cards |
| Border | `border-zinc-200` light / `border-zinc-800` dark — no shadows on cards |
| Shadow | Only on the top bar (when scrolled) and on the active sidebar item |
| Background | Light: `bg-white` (not gray) with subtle borders. Dark: `bg-zinc-950`. |
| Icon library | **Lucide** via CDN (`https://unpkg.com/lucide@latest`) — 16px in nav, 14px inline, 20px in empty states |

**Layout changes:**

- Sidebar gets icons + smaller text, active item is a subtle `bg-zinc-100` (light) or `bg-zinc-900` (dark) with a thin left accent bar
- Top bar becomes thinner (h-12 instead of h-14), with the dark mode toggle + user email on the right
- Container goes `max-w-6xl` (was `max-w-5xl`) but with tighter padding on cards
- Feed gets a subtle category pill instead of an underlined header
- Empty states get a Lucide icon in a soft circle, not an emoji

**Micro-interactions:**

- HTMX requests trigger a thin top progress bar (htmx-indicator on `<body>`)
- Cards have a 100ms `transition-colors` on hover (border darkens, no background change)
- Buttons get a subtle scale-down on `:active` (`active:scale-[0.98]`)
- Feed cards on load: subtle fade-in via Tailwind `animate-in fade-in duration-200`

**Dark mode:**

- Use Tailwind's `class` strategy (toggle by adding `dark` to `<html>`)
- Persist preference in `localStorage` under `theme` ('light' | 'dark' | 'system')
- Default to `system` (use `prefers-color-scheme`)
- Toggle button (sun/moon Lucide icon) lives in the top bar

### Constraints (do not break)

- **All 55 tests must still pass.** This is pure-visual; no route changes, no model changes, no form-name changes.
- **CDN-only, no JS build step.** Add Tailwind CDN (already there), Lucide CDN, Inter via Google Fonts. No npm, no PostCSS, no Vite.
- **All HTMX endpoints, form names, CSRF wiring, URL routes, and template variables stay identical.** This is a reskin.
- **Email template (`core/templates/digest.html.j2`) is NOT touched** — emails need their own inline-CSS optimization and shouldn't share styles with the dashboard.

### Phasing

One shot. There are only 8 templates and they share `base.html`, so a single coordinated pass keeps things consistent. Doing it in two passes risks half-styled pages.

---

## Part 2 — Prompt for Claude Code

Copy everything in the fenced block below into Claude Code at `~/Desktop/ai-news-aggregator`.

```
You are working in ~/Desktop/ai-news-aggregator on a Flask + HTMX + Tailwind (CDN) dashboard for an AI news aggregator. The project has 55 passing tests and is feature-complete. Your job is a PURE VISUAL REDESIGN of the web dashboard — no behavior changes, no route changes, no form-name changes, no model changes. All 55 tests must still pass when you're done.

## Goal
Modernize the dashboard from a 2020-era admin-panel look (emoji icons, generic blue, gray-on-white cards) to a 2025 Linear/Vercel/Raycast aesthetic: clean typography, monochrome neutrals with one accent, line icons, optional dark mode, tight spacing.

## Constraints — read carefully
1. **CDN only.** No npm, no build step, no PostCSS. Tailwind via CDN is fine (it's already there). Add Lucide icons via CDN and Inter via Google Fonts.
2. **Do not touch:** `core/templates/digest.html.j2` (that's the email template), any Python file in `app/` or `core/`, any test, any config, `run.py`, `Dockerfile`, `gunicorn_conf.py`.
3. **Preserve every:** route name (`url_for(...)` call), HTMX attribute (`hx-get`, `hx-post`, `hx-target`, `hx-swap`), form field `name` attribute, CSRF wiring (meta tag + hidden inputs + HTMX header hook), Jinja variable name, template block name, and `{% include %}` / `{% extends %}` relationship.
4. **All 55 tests pass.** Run `pytest` at the end and report the count.
5. **Files in scope:** only the 8 dashboard templates under `app/templates/` (`base.html`, `login.html`, `feed.html`, `feed_items.html`, `settings.html`, `settings_form.html`, `preview.html`, `archive.html`) and the `emails/magic_link.html` template (lightly polished — different rules though, since it's HTML email; keep inline styles only).

## Design tokens to use consistently
- **Body font:** Inter via Google Fonts (`<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">`). Set `font-family: 'Inter', ui-sans-serif, system-ui, sans-serif` on body; add `font-feature-settings: 'cv11', 'ss01';` for the modern Inter look.
- **Mono font:** JetBrains Mono — apply via `font-mono` to timestamps, source names, story counts.
- **Neutrals:** Tailwind `zinc-*` palette (NOT `gray`, NOT `slate`).
- **Accent:** `indigo-500` (primary buttons, links, active states), `indigo-600` on hover. For "Send to me" / success: `emerald-500` / `emerald-600`.
- **Radius:** `rounded-lg` (8px) everywhere. No `rounded-xl`, no `rounded-md`.
- **Borders, not shadows:** Cards use `border border-zinc-200` (light) / `dark:border-zinc-800` (dark). No box-shadows on cards. Only the sticky top bar gets a subtle border-bottom.
- **Backgrounds:** Body is `bg-white dark:bg-zinc-950`. Cards are `bg-white dark:bg-zinc-900/50`. Sidebar is `bg-zinc-50 dark:bg-zinc-900`.
- **Container:** `max-w-6xl` (was 5xl). Content padding `px-6 py-8`.

## Iconography
- Replace EVERY emoji (📡 ⚙️ 👁 🗃 📰 ✉ ⟳ 📭) with a Lucide icon.
- Add Lucide via CDN in base.html: `<script src="https://unpkg.com/lucide@latest"></script>` and call `lucide.createIcons()` after DOM ready AND after every HTMX swap (`document.body.addEventListener('htmx:afterSwap', () => lucide.createIcons())`).
- Icon syntax: `<i data-lucide="rss" class="w-4 h-4"></i>`.
- Mapping:
  - 📡 Feed → `rss` (sidebar 16px) / `inbox` (empty state 32px)
  - ⚙️ Settings → `settings`
  - 👁 Preview → `eye`
  - 🗃 Archive → `archive`
  - 📰 (top bar) → `newspaper` next to a wordmark "AI News"
  - ✉ Send to me → `send`
  - ⟳ Refresh → `refresh-cw` (with `class="animate-spin"` when htmx-request class is active)
  - 📭 Empty feed → `inbox` in a soft circle
  - ✅ Settings saved → `check-circle-2`

## Dark mode
- Tailwind config: enable dark mode with `class` strategy. Since you're on CDN, add this BEFORE the Tailwind script tag: `<script>tailwind.config = { darkMode: 'class' }</script>`.
- Add a theme toggle button in the top bar (right side). Three states: light, dark, system.
- Persist to `localStorage.theme`. On page load, before any render, run an inline script in `<head>` that reads `localStorage.theme` (or `matchMedia('(prefers-color-scheme: dark)')`) and adds `dark` class to `<html>` — this prevents the flash of unstyled content.
- Toggle script lives in base.html. Use Lucide icons `sun` / `moon` / `monitor` to indicate state.

## Per-template changes

### base.html
- Add the Inter + JetBrains Mono link, the dark-mode inline init script, the Tailwind config script (`darkMode: 'class'`), and the Lucide script.
- Top bar: `h-12`, `border-b border-zinc-200 dark:border-zinc-800`, no shadow. Left side: small `newspaper` icon + "AI News" wordmark in `font-semibold`. Right side: theme toggle button + user email in `text-xs text-zinc-500 font-mono`.
- Sidebar: `w-56`, `bg-zinc-50 dark:bg-zinc-900`, `border-r border-zinc-200 dark:border-zinc-800`. Each nav item: `flex items-center gap-2.5 px-3 py-1.5 rounded-md text-sm`. Active item: `bg-white dark:bg-zinc-800 text-zinc-900 dark:text-zinc-50 shadow-sm`. Inactive: `text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800/50`. Use Lucide icons at 16px.
- Add a thin HTMX progress bar at the top of `<body>`: a `<div>` styled `fixed top-0 left-0 h-0.5 bg-indigo-500 transition-all duration-300 z-50` that shows during HTMX requests (use `htmx-indicator` class pattern).
- Container: `max-w-6xl mx-auto px-6 py-8`.

### login.html
- Centered card, `max-w-sm`, `bg-white dark:bg-zinc-900` with `border border-zinc-200 dark:border-zinc-800` (NO shadow). Inside: small `newspaper` icon in a `w-10 h-10 rounded-lg bg-indigo-500/10 text-indigo-500` circle, then "AI News" heading in `text-lg font-semibold`, then a one-line subtitle in `text-sm text-zinc-500`.
- Email input: `bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-200 dark:border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent`.
- Button: `bg-indigo-500 hover:bg-indigo-600 active:scale-[0.98] text-white font-medium py-2 px-4 rounded-lg text-sm transition-all`.

### feed.html
- Page title in `text-2xl font-semibold tracking-tight` (was `text-xl font-bold`).
- Refresh button: secondary style — `bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-700 text-sm font-medium px-3 py-1.5 rounded-lg flex items-center gap-2`. Include `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i>`. Show spinning state when `.htmx-request` is on the form.

### feed_items.html
- Top meta line: `font-mono text-xs text-zinc-500`.
- Category header: a small pill `inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-100 dark:bg-zinc-800 text-xs font-medium text-zinc-700 dark:text-zinc-300 mb-3` followed by a thin `border-b border-zinc-200 dark:border-zinc-800 mb-4`. Drop the uppercase/tracking-widest treatment.
- Story card: `bg-white dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-800 rounded-lg p-4 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors`. Title in `text-[15px] font-medium leading-snug`. Link uses `text-zinc-900 dark:text-zinc-50 hover:text-indigo-500 dark:hover:text-indigo-400`. Meta row in `font-mono text-xs text-zinc-500`. Summary in `text-sm text-zinc-600 dark:text-zinc-400 leading-relaxed mt-2`.

### settings.html
- Title `text-2xl font-semibold tracking-tight`.

### settings_form.html
- "Saved" banner: change to a thin `border-l-4 border-emerald-500 bg-emerald-500/5 text-emerald-700 dark:text-emerald-400 px-4 py-2 rounded text-sm flex items-center gap-2` with a `check-circle-2` icon (no ✅).
- Section headers: `text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-4` (drop the bold-gray-400 look).
- Sections: `bg-white dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-800 rounded-lg p-6`.
- Checkboxes: `h-4 w-4 rounded border-zinc-300 dark:border-zinc-600 text-indigo-500 focus:ring-indigo-500`. Wrap each in a label with `hover:bg-zinc-50 dark:hover:bg-zinc-800/50 -mx-2 px-2 py-1.5 rounded-md transition-colors`.
- Number/text inputs: same style as the login email input above.
- Source rows: show category as a small pill (`bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 text-xs px-2 py-0.5 rounded`). Show weight in `font-mono text-xs text-zinc-500`.
- Save button: `bg-indigo-500 hover:bg-indigo-600 active:scale-[0.98]` (was blue-600).

### preview.html
- Title `text-2xl font-semibold tracking-tight`.
- "Send to me" button: emerald-500 with `send` Lucide icon (no ✉).
- iframe container: `border border-zinc-200 dark:border-zinc-800 rounded-lg overflow-hidden`.

### archive.html
- Title `text-2xl font-semibold tracking-tight`.
- Empty state: replace 🗃 with a `w-12 h-12 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center` containing `<i data-lucide="archive" class="w-6 h-6 text-zinc-400"></i>`. Headline `text-base font-medium text-zinc-700 dark:text-zinc-300`. Subtext `text-sm text-zinc-500`.
- List container: `bg-white dark:bg-zinc-900/40 border border-zinc-200 dark:border-zinc-800 rounded-lg divide-y divide-zinc-100 dark:divide-zinc-800`.
- Each row: hover with `hover:bg-zinc-50 dark:hover:bg-zinc-800/40`. Story count + date in `font-mono text-xs text-zinc-500`. Add a `chevron-right` Lucide icon on the right at 16px.

### archive_view.html
- Same title treatment + iframe container treatment as preview.html.

### emails/magic_link.html
- Light polish only — keep inline styles, keep it bulletproof for email clients. Make the button indigo (`#6366f1`) instead of whatever blue it is, and the body font `-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`. Don't add Lucide or external fonts here — email clients won't render them.

## After you're done
1. Run `pytest` and confirm 55/55 pass.
2. Start the app (`flask --app run.py run`) and visit `/login`, `/feed`, `/settings`, `/preview`, `/archive` in both light and dark mode. Take a screenshot of each if your environment allows.
3. Report back with:
   - Test count
   - A list of every file you changed
   - Anything you had to deviate from in this spec and why
   - Anything you noticed but didn't change

## STOP AND REPORT if:
- Any test fails — don't push through
- You discover a route/form/CSRF wiring you'd have to touch to make the visual change work — pause and ask
- You run low on context — stop, commit, and report what's left
```

---

## How to use this

1. Open Cursor or Claude Code at `~/Desktop/ai-news-aggregator`.
2. Paste the fenced block above as a single message.
3. When it reports back, verify by:
   - Running `pytest` yourself
   - Visiting each page in light + dark mode
   - Confirming the emoji icons are gone everywhere
4. If you want to tweak the accent color (indigo → violet, blue, teal, etc.) or the radius (rounded-lg → rounded-md for a tighter look), just ask it to swap those tokens — they're consistently named in the prompt.
