# Style Tag Removal & Brand Token Consolidation — Design

**Date:** 2026-04-27
**Status:** Approved (pending user review of this doc)
**Owner:** Louis-Jean Teitelbaum

## Goal

Eliminate the proliferation of inline `style="…"` attributes across the Jinja templates and consolidate brand colors into a single source of truth, so that:

- Changing a brand color is a one-line edit in one file.
- Recurring UI blocks (cards, page headers, empty states, form fields, stat tiles, section headings, table wrappers) are reusable Jinja partials, not copy-pasted markup.
- Templates use semantic class names instead of raw hex literals.
- The visual output is unchanged.

## Non-goals

- No Tailwind build step. The project stays no-build; `static/css/tailwind.css` continues to be a hand-curated static file.
- No typography scale collapse (option (c) from brainstorming). The risk of invisible drift in heading sizes/weights is too high without screenshot-diff infrastructure, which is out of scope.
- No visual redesign. This is a pure refactor.
- No new tests required for the refactor itself; the existing pytest suite must keep passing.

## Current state (baseline)

- ~1,409 inline `style="…"` attributes across ~30 templates.
- Top duplicated values: `color: #6B7280` (308×), `color: #1A1A1A` (149×), `font-variation-settings: 'SOFT' 0, 'WONK' 1` (149× — already applied globally in `base.html` to `h1-h6` and `.font-display`, so all inline copies are redundant), `border-color: #E5E7EB` (56×), `background-color: #F0F4F7` (56×).
- 11 brand colors used as raw hex literals throughout the templates.
- Two near-duplicate values that are almost certainly typos / inconsistencies:
  - `#F0F4F7` (56 uses) vs `#F0F4F8` (2 uses) — to be collapsed to `#F0F4F7`.
- Two semantically distinct pairs to be preserved as separate tokens:
  - `#1A1A1A` (body text) vs `#313131` (secondary/heading text)
  - `#E5E7EB` (border default) vs `#F3F4F6` (border subtle / divider)
- `static/css/app.css` already declares CSS custom properties (`--c-navy`, `--c-cream`, `--c-mute`, …) plus 5 semantic component classes (`.btn-navy`, `.btn-coral`, `.btn-ghost-navy`, `.input-soft`, `.input-coral`, `.sidebar-link`, `.btn-red`).
- `static/css/tailwind.css` is a hand-written static utility file. It exposes generic Tailwind utilities (`px-4`, `flex`, etc.) but does not expose brand-aware utilities. This is the root cause of the inline-hex problem: authors had no `bg-navy` or `text-mute` to reach for.
- 4 Jinja partials exist in `templates/components/`: `confirm_dialog.html`, `flash_messages.html`, `status_badge.html`, `structure_type_badge.html`.
- CSP allows `'unsafe-inline'` for styles (`app.py:28`), so inline `style=""` works today — but the project's recent direction (commit `2640ea0`, `47a8576`) has been to remove inline JS and tighten CSP. This refactor is the consistent next step for styles.

## Architecture: three layers

The refactored styling system has three layers, each with one job:

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1 — Tokens (static/css/app.css :root)             │
│  Single source of truth: colors, fonts, type features.   │
│  Any new color is added HERE first.                      │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │ var(--c-…)
                          │
┌──────────────────────────────────────────────────────────┐
│  Layer 2 — Utilities (static/css/tailwind.css)           │
│  Token-backed utility classes: text-mute, bg-navy,       │
│  border-soft, etc. Mirror of Tailwind's API.             │
│  Plus existing component classes in app.css:             │
│  .btn-navy, .input-soft, .sidebar-link, …                │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │ class="…"
                          │
┌──────────────────────────────────────────────────────────┐
│  Layer 3 — Components (templates/components/ui.html)     │
│  Jinja macros for recurring UI blocks: card,             │
│  page_header, empty_state, form_field, stat_tile,        │
│  section_heading, table_wrapper.                         │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │ {% call %} / {{ macro() }}
                          │
                  Templates (no hex literals)
```

**The hard rule that keeps this honest:** no template ever writes a hex literal. If a template needs a color, it goes through layers 1→2 (utility class) or 1→2→3 (component).

---

## Layer 1 — Token layer (`static/css/app.css`)

Replace the existing `:root` block with the consolidated set:

```css
:root {
  /* Brand */
  --c-navy:        #1A3A52;
  --c-navy-soft:   #F0F4F7;   /* was also #F0F4F8 — collapsed */
  --c-cream:       #F5F1E8;
  --c-cream-page:  #FAF7F2;   /* page bg, currently in base.html <style> */
  --c-coral:       #C4714A;
  --c-coral-strong:#E84B3A;
  --c-red-cta:     #B70102;   /* landing red button */

  /* Text */
  --c-text:        #1A1A1A;
  --c-text-soft:   #313131;
  --c-mute:        #6B7280;
  --c-mute-soft:   #9CA3AF;
  --c-disabled:    #D1D5DB;

  /* Surfaces & borders */
  --c-surface:     #FFFFFF;
  --c-border:      #E5E7EB;
  --c-border-soft: #F3F4F6;

  /* Status */
  --c-success:     #22C55E;
  --c-success-bg:  #DCFCE7;
  --c-success-fg:  #16A34A;
  --c-warning:     #F59E0B;
  --c-warning-bg:  #FEF3C7;
  --c-warning-fg:  #D97706;
  --c-danger:      #DC2626;
  --c-danger-bg:   #FEF2F2;
  --c-danger-fg:   #DC2626;

  /* Type */
  --font-display:      'Fraunces', serif;
  --font-body:         system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-feat-display: 'SOFT' 0, 'WONK' 1;
}
```

Move from `base.html`'s `<style>` block into `app.css`:

```css
html { background-color: var(--c-cream-page); color: var(--c-text); }
body { font-family: var(--font-body); }
h1, h2, h3, h4, h5, h6, .font-display {
  font-family: var(--font-display);
  font-variation-settings: var(--font-feat-display);
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(196, 113, 74, 0.25); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: rgba(196, 113, 74, 0.5); }
* { scrollbar-width: thin; scrollbar-color: rgba(196, 113, 74, 0.25) transparent; }
button, a, [role="button"], select, input[type="checkbox"], input[type="radio"] { cursor: pointer; }
```

Update existing component classes in `app.css` to consume tokens (already mostly do; the few that hard-code `#132B3E` etc. for hover stay since they're shade variants, not tokens themselves).

---

## Layer 2 — Utility layer (`static/css/tailwind.css`)

**Add** a new section at the end of `tailwind.css`:

```css
/* ============================================================
   30. Brand utilities (token-backed)
   ============================================================ */

/* Text */
.text-text       { color: var(--c-text); }
.text-text-soft  { color: var(--c-text-soft); }
.text-mute       { color: var(--c-mute); }
.text-mute-soft  { color: var(--c-mute-soft); }
.text-disabled   { color: var(--c-disabled); }
.text-navy       { color: var(--c-navy); }
.text-coral      { color: var(--c-coral); }
.text-danger     { color: var(--c-danger); }
.text-success    { color: var(--c-success-fg); }
.text-warning    { color: var(--c-warning-fg); }

/* Background */
.bg-cream        { background-color: var(--c-cream); }
.bg-cream-page   { background-color: var(--c-cream-page); }
.bg-navy         { background-color: var(--c-navy); }
.bg-navy-soft    { background-color: var(--c-navy-soft); }
.bg-coral        { background-color: var(--c-coral); }
.bg-success-soft { background-color: var(--c-success-bg); }
.bg-warning-soft { background-color: var(--c-warning-bg); }
.bg-danger       { background-color: var(--c-danger); }
.bg-danger-soft  { background-color: var(--c-danger-bg); }

/* Border */
.border-default  { border-color: var(--c-border); }
.border-soft     { border-color: var(--c-border-soft); }
.border-navy     { border-color: var(--c-navy); }

/* Hover/focus variants (replace existing arbitrary-value escapes) */
.hover\:bg-cream:hover     { background-color: var(--c-cream); }
.hover\:bg-navy-soft:hover { background-color: var(--c-navy-soft); }
.focus\:border-navy:focus  { border-color: var(--c-navy); }

/* Form accent (replaces inline style="accent-color: #1A3A52") */
.accent-navy { accent-color: var(--c-navy); }

/* Has-checked variants (replaces existing arbitrary-value escapes) */
.has-\[\:checked\]\:bg-navy:has(:checked)      { background-color: var(--c-navy); }
.has-\[\:checked\]\:bg-navy-soft:has(:checked) { background-color: var(--c-navy-soft); }

/* Icon size additions (for inline width:Npx;height:Npx that have no current utility) */
.w-3 { width: 0.75rem; }   /* 12px */
.h-3 { height: 0.75rem; }
```

**Remove** from `tailwind.css` (now superseded):
- `.text-dark { color: #1A1A1A }` → replaced by `.text-text`.
- `.hover\:bg-\[\#F5F1E8\]` → replaced by `.hover\:bg-cream`.
- `.focus\:border-\[\#1A3A52\]` → replaced by `.focus\:border-navy`.
- `.has-\[\:checked\]\:bg-\[\#1A3A52\]`, `.has-\[\:checked\]\:bg-\[\#F0F4F7\]` → replaced by `.has-\[\:checked\]\:bg-navy`, `.has-\[\:checked\]\:bg-navy-soft`.

The hard-coded `.bg-coral-red { #FF5455 }` (notification badge) **stays** — it's a distinct accent color, not the brand coral. Worth keeping isolated.

**Remove** the `<style>` block from `base.html` entirely (its content moves to `app.css` per Layer 1). Remove inline `style="background-color: #F5F1E8;"` from `<body>` (replaced by the `bg-cream-page` style applied to `html` in `app.css`, plus class on `<body>` if needed).

---

## Layer 3 — Component layer (`templates/components/ui.html`)

Single new file with seven macros, imported per-template as:

```jinja
{% from "components/ui.html" import card, page_header, empty_state, form_field, stat_tile, section_heading, table_wrapper %}
```

### `card(class="")`
White surface with rounded corners, soft border, padding. Block content via `{% call %}`.

```jinja
{% macro card(class="") %}
  <div class="bg-white rounded-2xl border border-soft p-6 {{ class }}">{{ caller() }}</div>
{% endmacro %}
```

### `page_header(title, subtitle=None)`
Page title + optional subtitle + optional right-aligned action slot via `{% call %}`.

```jinja
{% macro page_header(title, subtitle=None) %}
  <header class="mb-8 flex items-start justify-between gap-4">
    <div>
      <h1 class="font-display text-3xl font-bold text-text">{{ title }}</h1>
      {% if subtitle %}<p class="mt-2 text-mute">{{ subtitle }}</p>{% endif %}
    </div>
    {% if caller %}<div class="flex items-center gap-2">{{ caller() }}</div>{% endif %}
  </header>
{% endmacro %}
```

### `empty_state(icon, title, body=None)`
Centered icon + heading + helper text + optional CTA via `{% call %}`.

### `form_field(label, name, type="text", value="", required=False, help=None, error=None)`
Standard form input with label, helper text, error message. Plus sibling macros `form_textarea` and `form_select` with the same shape.

### `stat_tile(label, value, icon=None, tone="navy")`
Dashboard stat tile with label, big value, optional icon. `tone` ∈ {navy, cream, white}.

### `section_heading(label)`
Small uppercase tracked label above a content block.

### `table_wrapper(class="")`
Wraps a table with the standard surface, overflow handling, and rounded corners. Body content via `{% call %}`. Header row classes documented in the macro file's leading comment block: `<thead class="bg-cream"><tr><th class="text-left text-xs uppercase tracking-wider text-mute font-semibold px-4 py-3">…</th></tr></thead>`; body rows: `<tr class="border-t border-soft">`.

(The full Jinja source for each macro is in the brainstorming notes; final wording is finalized during PR 1 implementation.)

---

## Migration sweep — replacement table

The PR-2 sweep is dominated by mechanical 1:1 replacements. Driving table:

| Inline style | Count | Replacement | Notes |
|---|---|---|---|
| `color: #6B7280` | 308 | `class="text-mute"` | |
| `color: #1A1A1A` | 149 | `class="text-text"` | |
| `color: #1A1A1A; font-variation-settings: 'SOFT' 0, 'WONK' 1` | 85 | `class="text-text"` | font feature is global |
| `font-variation-settings: 'SOFT' 0, 'WONK' 1` | 64 | **delete** | redundant with global rule |
| `border-color: #E5E7EB` | 56 | `class="border-default"` (with `border` for width) | |
| `background-color: #F0F4F7` and `#F0F4F8` | 58 | `class="bg-navy-soft"` | typo collapse |
| `background-color: #F5F1E8` | 44 | `class="bg-cream"` | |
| `color: #1A3A52` | 35 | `class="text-navy"` | |
| `color: #313131` | 33 | `class="text-text-soft"` | |
| `background-color: #F5F1E8; color: #313131` | 29 | `class="bg-cream text-text-soft"` | |
| `border-top: 1px solid #F3F4F6` | 26 | `class="border-t border-soft"` | |
| `background-color: #1A3A52; color: #FFFFFF` | 18 | `class="bg-navy text-white"` | |
| `accent-color: #1A3A52` | 19 | `class="accent-navy"` | |
| `color: #DC2626` | 14 | `class="text-danger"` | |
| `background-color: #F5F1E8; min-height: 100vh` | 14 | `class="bg-cream min-h-screen"` | |
| `border-bottom: 1px solid #F3F4F6` | 11 | `class="border-b border-soft"` | |
| `background-color: #1A3A52` | 10 | `class="bg-navy"` | |
| `background-color: #F5F1E8; color: #1A3A52` | 9 | `class="bg-cream text-navy"` | |
| `background-color: #DCFCE7; color: #16A34A` | 9 | `class="bg-success-soft text-success"` | |
| `border: 1px solid #1A3A52; color: #1A3A52` | 6 | `class="border border-navy text-navy"` | |
| `background-color: #DC2626; color: #FFFFFF` | 4 | `class="bg-danger text-white"` | |
| `border-top: 1px solid #E5E7EB` | 4 | `class="border-t border-default"` | |
| Icon `width:Npx;height:Npx;color:#…` (~120 occurrences) | varies | `class="w-N h-N text-…"` | use existing Tailwind w/h utilities; add `w-3`/`h-3` for 12px |
| `display: none` | ~22 | `class="hidden"` | for JS-toggled, ensure JS uses `classList.toggle("hidden")` |

**Special cases that get a partial or component class instead of a utility:**

- `padding: 54px 24px 48px; max-width: 1020px; margin: 0 auto;` (14×, content frame on landing) → wrap in a div with utility classes; if the exact `54px` matters, add a one-off class `.frame-landing` to `app.css`.
- `max-width:520px; margin:80px auto; text-align:center; padding:32px` (4×, error pages 404/500) → utility classes `max-w-lg mx-auto my-20 text-center p-8`.
- `display:inline-block; background:#1A3A52; color:#FFF; padding:10px 20px; border-radius:9999px; font-weight:bold; font-size:14px` (4×, error-page CTA) → new component class `.btn-navy-pill` in `app.css`.
- `width: 241px` (sidebar) → add a CSS variable `--w-sidebar: 241px` and either utility `.w-sidebar` or keep a single inline `style="width:var(--w-sidebar)"` in `base.html` only.
- `border-bottom: 1px solid #F3F4F6` on mobile topbar in `base.html` → `class="border-b border-soft"`.

---

## Delivery shape — two PRs

### PR 1 — Foundations + components (zero visual change)

**Branch:** `refactor/style-tokens-foundations`

Additive only. After this PR, the running app should look pixel-identical because nothing yet consumes the new utilities/components.

Scope:
1. `static/css/app.css`: replace `:root` with consolidated token set. Add `html`/`body`/`h1-h6`/scrollbar/`button` rules moved from `base.html`. Update existing component classes to consume tokens where they currently hard-code hex.
2. `static/css/tailwind.css`: append the new "Brand utilities" section. Do NOT yet remove the legacy `text-dark` / arbitrary-value escapes (templates still use them — they'll be cleaned up at the end of PR 2). Add `w-3`/`h-3`.
3. `templates/components/ui.html`: new file with the seven macros + leading docstring documenting usage and the table-row/header conventions.
4. `base.html`: remove the `<style>` block (its content lives in `app.css` now). Remove the inline `style="background-color: #F5F1E8;"` from `<body>` (handled by `bg-cream-page` on `html`). This is the only template change in PR 1, and it has zero visual effect.

Verification:
- `pytest` passes (existing route-render tests).
- Manual smoke: open dashboard / requests list / landing in dev. Visually identical to baseline.

### PR 2 — Template sweep

**Branch:** `refactor/style-tokens-sweep`

One commit per area to keep the diff scannable:

1. `auth/` (login, signup) — small, isolated, easy first.
2. `landing.html` + `errors/` — public pages.
3. `client/` — biggest area. Sub-commits per sub-folder if needed (`requests/`, `orders/`, `messages/`, top-level).
4. `caterer/`.
5. `admin/`.
6. `components/` (`status_badge.html`, etc.) — adopt new utilities; many already only use classes.
7. **Final commit:** delete now-unused legacy classes from `tailwind.css`: `.text-dark`, `.hover\:bg-\[\#F5F1E8\]`, `.focus\:border-\[\#1A3A52\]`, `.has-\[\:checked\]\:bg-\[\#1A3A52\]`, `.has-\[\:checked\]\:bg-\[\#F0F4F7\]`. Confirmed unused via grep.

Per-area workflow:
1. Pre-capture: open the area's main pages in dev, take a screenshot for baseline.
2. Apply the replacement table mechanically.
3. Look for opportunities to adopt the new macros (card, page_header, empty_state, etc.) — the goal is "at least one usage per macro by end of sweep" but the priority is the inline-style elimination.
4. Run `pytest`.
5. Re-open the same pages. Eyeball-diff against the baseline screenshot.
6. Commit.

---

## Verification strategy

### What I can guarantee

- **Algebraic CSS equivalence** per replacement: each inline style I remove maps to a class whose computed CSS reproduces the same property values. The replacement table above is the proof.
- The token layer is the single source of truth: `grep -rE '#[0-9A-Fa-f]{3,6}' templates/` returns 0 hits at the end of PR 2 (zero hex literals in templates).
- No regressions in the existing pytest route-rendering suite.

### What I cannot guarantee without extra infra

- Pixel-identical screenshots across all pages × all roles × all breakpoints. The project has no Playwright / visual-regression harness today, and adding one is a separate sub-project (out of scope).

### Side-by-side dev verification (per user request)

After PR 2 is implemented locally, spin up two dev environments:
- **Pre-changes:** the current `dev` branch on its own port (e.g., 8000).
- **Post-changes:** the refactor branch on a different port (e.g., 8001).

This lets the user open the same URL in two tabs and visually diff per page across roles. Implementation note: docker-compose can be invoked twice with different project names and host port mappings, or two `flask run` instances against the same DB on different ports. Detailed steps belong in the implementation plan.

### Final success criteria

1. `grep -rE 'style="[^"]*#[0-9A-Fa-f]+' templates/` returns 0.
2. `grep -rE 'style="[^"]*color:|background-color:|border-color:' templates/` returns 0.
3. `grep -rE "font-variation-settings" templates/` returns 0.
4. All brand colors live exactly once, in `:root` of `app.css`. Changing `--c-navy` recolors the entire app.
5. The 7 new macros are imported from `components/ui.html` and used in at least one template each.
6. `pytest` passes.
7. Side-by-side visual comparison (per area) shows no perceptible difference.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Class-vs-class cascade order surprises (a class added later in `tailwind.css` might lose to one declared earlier when conflicts exist) | The new utilities are added in a clearly-marked block at the end of `tailwind.css`; conflicts are unlikely because the previous patterns used inline style (specificity 1000) and we're replacing with a single class. Spot-check during sweep. |
| JS that toggles `style.display` directly (not via `classList`) | Audit `static/js/app.js` for `.style.display = …`; convert to `classList.toggle("hidden")` as part of PR 2. |
| Templates with locally-different shades I miss collapsing | The replacement table only collapses values I've audited; anything not on the table stays untouched and gets a manual judgment call during the sweep. |
| Macro adoption diverging from existing markup (e.g., `card` macro slightly different from existing card markup) | The macros are defined to match the most common existing form. When a template's existing markup differs, prefer leaving it alone over forcing it into the macro. |
| User dislikes a specific tradeoff after seeing it live | PR 1 is reversible (additive only). PR 2 is per-area-commit so individual areas can be reverted without losing the foundation. |

## Open questions resolved during brainstorming

- **Build step?** No — option (C) from brainstorming. Stay no-build, lean on `app.css` semantic component classes plus token-backed utilities in `tailwind.css`.
- **Color harmonization?**
  - Text: keep two — `--c-text` (`#1A1A1A`) for body, `--c-text-soft` (`#313131`) for secondary.
  - Navy-soft: collapse `#F0F4F8` (2 uses) into `#F0F4F7` (56 uses).
  - Borders: keep two — `--c-border` (`#E5E7EB`), `--c-border-soft` (`#F3F4F6`).
- **Componentization scope?** Option (b) — moderate. Seven macros: card, page_header, empty_state, form_field, stat_tile, section_heading, table_wrapper. No typography scale collapse.
- **Delivery?** Option (b) — two PRs. Foundations first (additive, zero visual risk), template sweep second.
- **Verification?** Side-by-side dev environments comparing pre-/post- branches per area, plus the algebraic-equivalence guarantees and the existing pytest suite.
