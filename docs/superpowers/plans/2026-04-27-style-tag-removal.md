# Style Tag Removal & Brand Token Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate ~1,409 inline `style="…"` attributes across the Jinja templates, consolidate brand colors into a single source of truth (`:root` in `app.css`), introduce token-backed semantic utility classes and 7 reusable Jinja macros, with no visible visual change.

**Architecture:** Three layers — Tokens (`app.css :root` CSS custom properties), Utilities (semantic class names in `app.css`, never `tailwind.css`), Components (`templates/components/ui.html` Jinja macros). `tailwind.css` stays pristine and regenerable.

**Tech Stack:** Flask + Jinja2 templates, hand-written `tailwind.css` (no build step), CSS custom properties, docker-compose for dev.

**Spec:** `docs/superpowers/specs/2026-04-27-style-tag-removal-design.md` (read before starting).

**Delivery:** Two PRs — PR 1 = Foundations + components (additive, zero visual risk). PR 2 = Template sweep + final cleanup.

---

## Important context for the engineer

### Why no new tests

This is a pure refactor. The spec explicitly says "no new tests required for the refactor itself; the existing pytest suite must keep passing." Verification is:

1. **Algebraic CSS equivalence per replacement.** Every inline style removed maps to a class whose computed CSS produces the same property values.
2. **Existing pytest suite** (`docker compose exec app pytest`) — covers route rendering and core behavior. Must stay green.
3. **Side-by-side visual diff** — Phase 0 sets up two running app instances (pre-changes and post-changes) on different ports so the user can eyeball the same URL in two browser tabs.

### Why JS-driven `.style.X = …` is out of scope

`static/js/wizard.js`, `signup.js`, `app.js` set inline styles via JS (e.g., `section.style.display = 'block'`, `tab.style.color = '#6B7280'`). This refactor is **template-only**.

Critical implication: when converting template `style="display: none"` → `class="hidden"`, JS that subsequently sets `element.style.display = 'block'` keeps working — inline style set via JS wins over the class. So the conversion is safe even without touching the JS. JS-driven inline styles are noted as a follow-up for a separate refactor.

### The replacement table (reference for Phase 2)

This table drives every per-template sweep. Keep it open.

| Inline style | Replacement | Notes |
|---|---|---|
| `style="color: #6B7280"` | `class="… text-mute"` | append to existing class list |
| `style="color: #1A1A1A"` | `class="… text-text"` | |
| `style="color: #1A1A1A; font-variation-settings: 'SOFT' 0, 'WONK' 1"` | `class="… text-text"` | drop font-variation; global rule covers it |
| `style="font-variation-settings: 'SOFT' 0, 'WONK' 1"` | **delete attribute entirely** | redundant with global rule on h1-h6 / .font-display |
| `style="border-color: #E5E7EB"` | `class="… border-default"` | |
| `style="background-color: #F0F4F7"` | `class="… bg-navy-soft"` | |
| `style="background-color: #F0F4F8"` | `class="… bg-navy-soft"` | typo collapse |
| `style="background-color: #F5F1E8"` | `class="… bg-cream"` | |
| `style="color: #1A3A52"` (or with trailing `;`) | `class="… text-navy"` | |
| `style="color: #313131"` | `class="… text-text-soft"` | |
| `style="background-color: #F5F1E8; color: #313131"` | `class="… bg-cream text-text-soft"` | |
| `style="border-top: 1px solid #F3F4F6"` | `class="… border-t border-soft"` | |
| `style="background-color: #1A3A52; color: #FFFFFF"` | `class="… bg-navy text-white"` | |
| `style="accent-color: #1A3A52"` | `class="… accent-navy"` | |
| `style="color: #DC2626"` (or trailing `;`) | `class="… text-danger"` | |
| `style="background-color: #F5F1E8; min-height: 100vh;"` | `class="… bg-cream min-h-screen"` | |
| `style="border-bottom: 1px solid #F3F4F6"` | `class="… border-b border-soft"` | |
| `style="background-color: #1A3A52"` | `class="… bg-navy"` | |
| `style="background-color: #F5F1E8; color: #1A3A52"` | `class="… bg-cream text-navy"` | |
| `style="background-color: #DCFCE7; color: #16A34A"` | `class="… bg-success-soft text-success"` | |
| `style="border: 1px solid #1A3A52; color: #1A3A52"` | `class="… border border-navy text-navy"` | |
| `style="background-color: #DC2626; color: #FFFFFF"` | `class="… bg-danger text-white"` | |
| `style="border-top: 1px solid #E5E7EB"` | `class="… border-t border-default"` | |
| `style="color: #6B7280;"` (with trailing semicolon) | same as no-semi version | |
| `style="color: #9CA3AF;"` | `class="… text-mute-soft"` | |
| `style="color: #C4714A;"` | `class="… text-coral"` | |
| `style="background: #F5F1E8;"` (note `background` shorthand) | `class="… bg-cream"` | |
| `style="background: #1A3A52;"` | `class="… bg-navy"` | |
| `style="background: #F0F4F8; color: #1A3A52;"` | `class="… bg-navy-soft text-navy"` | |
| Icon size `style="width:Npx;height:Npx;color:#…"` (12/14/16/18/24/32/48px) | `class="… w-N h-N text-…"` | use existing Tailwind sizes; for 12px add `w-3`/`h-3` to app.css |
| `style="display: none;"` or `style="display:none;"` | `class="… hidden"` | safe even when JS later toggles via `.style.display` |
| `style="display: none; background-color: #1A3A52; color: #FFFFFF"` | `class="… hidden bg-navy text-white"` | |
| `style="display: none; border: 1px solid #1A3A52; color: #1A3A52"` | `class="… hidden border border-navy text-navy"` | |
| `style="border: 2px solid #E5E7EB"` | `class="… border-2 border-default"` | add `.border-2 { border-width: 2px }` to app.css if not present |

**One-off styles that get a custom class instead** (handle case-by-case during sweep):
- `style="padding: 54px 24px 48px; max-width: 1020px; margin: 0 auto;"` (landing content frame) → keep inline OR add `.frame-landing` to `app.css`. Discuss in commit message.
- `style="max-width:520px;margin:80px auto;text-align:center;padding:32px"` (errors/404, 500) → utility classes `max-w-lg mx-auto my-20 text-center p-8`.
- `style="display:inline-block;background:#1A3A52;color:#FFF;padding:10px 20px;border-radius:9999px;text-decoration:none;font-weight:bold;font-size:14px"` (error CTA) → utility classes `inline-block bg-navy text-white px-5 py-2.5 rounded-full font-bold text-sm`.
- `style="width: 241px"` (sidebar in `base.html`) → leave inline for now; refactoring to a CSS variable couples with `app.js:22`.
- `style="margin-left: 0;"` (main element in `base.html`) → leave inline (controlled by `app.js`).
- Anything containing `rgba(...)` → use the existing utility if present; otherwise add a token + utility.

---

## File Structure

### Files created

- `templates/components/ui.html` — single file holding all 7 Jinja macros. One file, not seven, because (a) they share conventions, (b) one `{% from … import … %}` line per consuming template is less noisy than seven `{% include %}` lines, (c) macros need parameters which `{% include %}` doesn't naturally support.
- `docs/superpowers/notes/baseline-screenshots/` — directory for pre-refactor screenshots used in side-by-side diff.

### Files modified

- `static/css/app.css` — replaces `:root`, adds `html`/`body`/`h1-h6`/scrollbar rules from `base.html`, appends "Brand utilities" block, appends "Legacy custom — to remove" block.
- `static/css/tailwind.css` — removes 7 custom rules + `.bg-coral-red`; updates header comment.
- `templates/base.html` — removes `<style>` block; removes inline body bg.
- All ~30 templates listed in Phase 2 — inline-style sweep.
- (At end) `static/css/app.css` — deletes "Legacy custom" block.

### Files NOT modified (in scope)

- `static/js/*.js` — all JS-driven inline styles are out of scope.
- Python source — no behavior change.
- Tests — no new tests; existing suite must keep passing.

---

## Phase 0 — Side-by-side dev environment setup

**Goal:** two running app instances, one on the unmodified `dev` branch, one on the refactor branch, on different ports, with isolated databases. So the user can compare any URL in two tabs.

### Task 0.1: Capture baseline branch state

**Files:**
- None (read-only)

- [ ] **Step 1: Confirm starting branch is clean and on `dev`**

```bash
git status
git branch --show-current
```
Expected: working tree clean, branch is `dev`.

- [ ] **Step 2: Note the current commit for later reference**

```bash
git rev-parse HEAD > /tmp/style-refactor-baseline-sha.txt
cat /tmp/style-refactor-baseline-sha.txt
```
Expected: a SHA echoed back. This is the "pre-changes" baseline.

### Task 0.2: Create the refactor worktree

**Files:**
- New worktree at `../traiteurs-style-refactor` on branch `refactor/style-tokens-foundations`.

- [ ] **Step 1: Create the worktree and branch in one command**

```bash
git worktree add ../traiteurs-style-refactor -b refactor/style-tokens-foundations
```
Expected: `Preparing worktree (new branch 'refactor/style-tokens-foundations')` and `HEAD is now at <baseline-sha>`.

- [ ] **Step 2: Verify the worktree is independent**

```bash
git worktree list
```
Expected: two entries — the original at `traiteurs/` on `dev`, and the new one at `traiteurs-style-refactor/` on `refactor/style-tokens-foundations`.

### Task 0.3: Bring up the "pre-changes" instance on port 8000

**Files:**
- None new; uses existing `docker-compose.yml` from the original checkout.

- [ ] **Step 1: From the original checkout, bring up the stack with project name `traiteurs-pre`**

```bash
cd /Users/louije/Development/gip/traiteurs
COMPOSE_PROJECT_NAME=traiteurs-pre HOST_PORT=8000 docker compose up -d
```
Expected: `app` and `db` services start; the named volume `traiteurs-pre_pgdata` is created (isolated from any other compose stack).

- [ ] **Step 2: Wait for healthy DB and seed**

```bash
COMPOSE_PROJECT_NAME=traiteurs-pre docker compose exec app python init_db.py
COMPOSE_PROJECT_NAME=traiteurs-pre docker compose exec app python seed_data.py
```
Expected: tables created, seed data loaded.

- [ ] **Step 3: Open http://localhost:8000/ and confirm the landing page renders**

Manual check. Log in as `alice@acme-solutions.fr` / `password123`. Confirm the dashboard loads. This is the pre-changes baseline — leave it running for the rest of the refactor.

### Task 0.4: Bring up the "post-changes" instance on port 8001

**Files:**
- None new; uses the new worktree's `docker-compose.yml` (identical at this point).

- [ ] **Step 1: From the refactor worktree, bring up the stack with project name `traiteurs-post`**

```bash
cd /Users/louije/Development/gip/traiteurs-style-refactor
COMPOSE_PROJECT_NAME=traiteurs-post HOST_PORT=8001 docker compose up -d
```
Expected: `app` and `db` services start under a separate project namespace; isolated DB volume `traiteurs-post_pgdata`.

- [ ] **Step 2: Seed the post-changes DB**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app python init_db.py
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app python seed_data.py
```

- [ ] **Step 3: Open http://localhost:8001/ and confirm identical render to port 8000**

Manual check. Side-by-side in two tabs. Both must look identical (they're the same code). If they don't, stop and investigate before going further.

### Task 0.5: Capture baseline screenshots of key pages

**Files:**
- Create: `docs/superpowers/notes/baseline-screenshots/` directory and ~10 screenshots.

- [ ] **Step 1: Create the directory in the refactor worktree**

```bash
mkdir -p /Users/louije/Development/gip/traiteurs-style-refactor/docs/superpowers/notes/baseline-screenshots
```

- [ ] **Step 2: From port 8000, capture screenshots of the sentinel pages**

Use the OS screenshot tool (macOS: ⌘⇧4 then space then click window). Save each as PNG with the suggested name into the directory above:

- `landing.png` — http://localhost:8000/
- `auth-login.png` — http://localhost:8000/auth/login
- `auth-signup.png` — http://localhost:8000/auth/signup
- `client-dashboard.png` — log in as alice, http://localhost:8000/client/dashboard
- `client-requests-new.png` — http://localhost:8000/client/requests/new
- `client-requests-detail.png` — open one request from the list
- `client-orders-detail.png` — open one order from the list
- `caterer-dashboard.png` — log out, log in as `contact@saveurs-solidaires.fr` / `password123`
- `caterer-quote-editor.png` — open a request in the caterer's queue, click "Devis"
- `admin-qualification-detail.png` — log in as `admin@traiteurs-engages.fr` / `admin`, open one pending caterer
- `error-404.png` — visit http://localhost:8000/this-does-not-exist

- [ ] **Step 3: Commit the baseline screenshots in the refactor worktree**

```bash
cd /Users/louije/Development/gip/traiteurs-style-refactor
git add docs/superpowers/notes/baseline-screenshots/
git commit -m "docs: baseline screenshots for style refactor visual diff"
```
Expected: clean commit on `refactor/style-tokens-foundations`.

---

## Phase 1 — PR 1: Foundations + components

All work happens in the `traiteurs-style-refactor` worktree. The "pre-changes" instance on port 8000 is the live baseline.

### Task 1.1: Replace `:root` in `app.css` with consolidated tokens

**Files:**
- Modify: `static/css/app.css` (lines 1-15 currently hold `:root`)

- [ ] **Step 1: Replace the `:root` block at the top of `app.css`**

Find the existing block (lines 1-15):

```css
/* Brand palette */
:root {
  --c-navy: #1A3A52;
  --c-navy-soft: #F0F4F8;
  --c-cream: #F5F1E8;
  --c-coral: #C4714A;
  --c-coral-strong: #E84B3A;
  --c-text: #1A1A1A;
  --c-mute: #6B7280;
  --c-mute-soft: #9CA3AF;
  --c-border: #E5E7EB;
  --c-border-soft: #F3F4F6;
  --c-success: #22C55E;
  --c-danger: #DC2626;
}
```

Replace with:

```css
/* ============================================================
   Brand tokens — single source of truth for color and type.
   Any new color is added HERE first.
   ============================================================ */
:root {
  /* Brand */
  --c-navy:        #1A3A52;
  --c-navy-soft:   #F0F4F7;   /* was also #F0F4F8 — typo collapsed */
  --c-cream:       #F5F1E8;
  --c-cream-page:  #FAF7F2;   /* page background */
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

/* Base element styles (moved from base.html <style>) */
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

- [ ] **Step 2: Verify nothing breaks at this point**

The existing component classes already reference these CSS variables; they keep working. `base.html` still has its own `<style>` block — that gets removed in Task 1.4.

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```
Open http://localhost:8001/ — should still look identical to http://localhost:8000/.

### Task 1.2: Append "Brand utilities" block to `app.css`

**Files:**
- Modify: `static/css/app.css` (append at end)

- [ ] **Step 1: Append the brand utilities block**

After all existing component classes (after `.btn-red:hover { … }`), append:

```css
/* ============================================================
   Brand utilities (token-backed)
   Mirror Tailwind's API but resolve to brand tokens.
   These live HERE, not in tailwind.css, so tailwind.css
   stays regenerable.
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
.border-2        { border-width: 2px; }

/* Hover/focus variants */
.hover\:bg-cream:hover     { background-color: var(--c-cream); }
.hover\:bg-navy-soft:hover { background-color: var(--c-navy-soft); }
.focus\:border-navy:focus  { border-color: var(--c-navy); }

/* Form accent */
.accent-navy { accent-color: var(--c-navy); }

/* Has-checked variants */
.has-\[\:checked\]\:bg-navy:has(:checked)      { background-color: var(--c-navy); }
.has-\[\:checked\]\:bg-navy-soft:has(:checked) { background-color: var(--c-navy-soft); }

/* Stock Tailwind classes the original tailwind.css scan missed */
.w-3 { width: 0.75rem; }
.h-3 { height: 0.75rem; }

/* Notification badge accent (project-specific, was in tailwind.css) */
.bg-coral-red { background-color: #FF5455; }
```

### Task 1.3: Append "Legacy custom — to remove" block to `app.css` and clean `tailwind.css`

**Files:**
- Modify: `static/css/app.css` (append at end)
- Modify: `static/css/tailwind.css` (remove 7 rules; update header)

- [ ] **Step 1: Append the legacy block to `app.css`**

```css
/* ============================================================
   Legacy custom — to remove
   Repatriated from tailwind.css to keep that file regenerable.
   PR 2's final commit deletes this block once no template
   references these names.
   ============================================================ */
.text-dark { color: var(--c-text); }
.hover\:bg-\[\#F5F1E8\]:hover { background-color: var(--c-cream); }
.focus\:border-\[\#1A3A52\]:focus { border-color: var(--c-navy); }
.has-\[\:checked\]\:bg-\[\#1A3A52\]:has(:checked) { background-color: var(--c-navy); }
.has-\[\:checked\]\:bg-\[\#F0F4F7\]:has(:checked) { background-color: var(--c-navy-soft); }
.has-\[\:checked\]\:bg-white:has(:checked) { background-color: #ffffff; }
.has-\[\:checked\]\:text-white:has(:checked) { color: #ffffff; }
```

- [ ] **Step 2: Remove the same rules from `tailwind.css`**

In `static/css/tailwind.css`, delete:

- `.text-dark { color: #1A1A1A; }` (in the "Text colors" section, ~line 491)
- `.bg-coral-red { background-color: #FF5455; }` (in "Background colors", ~line 509)
- `.hover\:bg-\[\#F5F1E8\]:hover { background-color: #F5F1E8; }` (~line 665)
- `.focus\:border-\[\#1A3A52\]:focus { border-color: #1A3A52; }` (~line 677)
- `.has-\[\:checked\]\:bg-\[\#1A3A52\]:has(:checked) { background-color: #1A3A52; }` (~line 684)
- `.has-\[\:checked\]\:bg-\[\#F0F4F7\]:has(:checked) { background-color: #F0F4F7; }` (~line 685)
- `.has-\[\:checked\]\:bg-white:has(:checked) { background-color: #ffffff; }` (~line 686)
- `.has-\[\:checked\]\:text-white:has(:checked) { color: #ffffff; }` (~line 687)

Also remove the trailing comment block (`/* hover:bg-[#F5F1E8] — already in hover section */` etc., ~lines 755-758) — it's stale.

- [ ] **Step 3: Update the header comment of `tailwind.css`**

Replace lines 1-4:

```css
/*
 * Static Tailwind CSS for Les Traiteurs Engages
 * Generated from template class scan — replaces cdn.tailwindcss.com
 */
```

with:

```css
/*
 * Static Tailwind CSS for Les Traiteurs Engages
 * Generated from template class scan — replaces cdn.tailwindcss.com
 *
 * DO NOT HAND-EDIT. Custom utilities and components live in app.css.
 * To regenerate: re-scan templates for class= attributes and rebuild
 * this file from a fresh Tailwind output.
 */
```

- [ ] **Step 4: Verify visual identity at port 8001**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```
Open http://localhost:8001/. Compare with port 8000. Must look identical (the rules moved file, but resolve identically). Check at minimum: landing page (uses `text-dark`), client dashboard sidebar hover (uses `hover:bg-[#F5F1E8]`), client/requests/new wizard radio cards (use `has-[:checked]:bg-[#1A3A52]`).

### Task 1.4: Strip the `<style>` block from `base.html`

**Files:**
- Modify: `templates/base.html` (lines 13-26 = `<style>` block, line 30 = body inline bg)

- [ ] **Step 1: Remove lines 13-26 (the entire `<style>…</style>` block)**

Delete:

```html
  <style>
    html { background-color: #FAF7F2; color: #1A1A1A; }
    body { font-family: system-ui, sans-serif; }
    h1, h2, h3, h4, h5, h6, .font-display {
      font-family: 'Fraunces', serif;
      font-variation-settings: 'SOFT' 0, 'WONK' 1;
    }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: #C4714A40; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #C4714A80; }
    * { scrollbar-width: thin; scrollbar-color: #C4714A40 transparent; }
    button, a, [role="button"], select, input[type="checkbox"], input[type="radio"] { cursor: pointer; }
  </style>
```

- [ ] **Step 2: Remove the inline body background**

Find:

```html
<body class="min-h-screen" style="background-color: #F5F1E8;">
```

Replace with:

```html
<body class="min-h-screen bg-cream">
```

- [ ] **Step 3: Verify visual identity at port 8001**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```
Open http://localhost:8001/. Compare side-by-side with port 8000. Must be identical: page background still cream, headings still Fraunces with SOFT 0 WONK 1, scrollbar still coral-tinted, cursor still pointer on buttons.

### Task 1.5: Create `templates/components/ui.html` with the 7 macros

**Files:**
- Create: `templates/components/ui.html`

- [ ] **Step 1: Create the file with all macros**

```jinja
{#
  UI macros — reusable building blocks for templates.

  Usage:
    {% from "components/ui.html" import card, page_header, empty_state, form_field, form_textarea, form_select, stat_tile, section_heading, table_wrapper %}

  Conventions:
    - Macros use only token-backed utility classes (text-mute, bg-navy, border-soft, …) defined in static/css/app.css.
    - Macros never write hex literals.
    - For table_wrapper: head row is `<thead class="bg-cream">` with `<th class="text-left text-xs uppercase tracking-wider text-mute font-semibold px-4 py-3">`; body rows are `<tr class="border-t border-soft">`.
#}

{% macro card(class="") %}
  <div class="bg-white rounded-2xl border border-soft p-6 {{ class }}">
    {{ caller() }}
  </div>
{% endmacro %}

{% macro page_header(title, subtitle=None) %}
  <header class="mb-8 flex items-start justify-between gap-4">
    <div>
      <h1 class="font-display text-3xl font-bold text-text">{{ title }}</h1>
      {% if subtitle %}<p class="mt-2 text-mute">{{ subtitle }}</p>{% endif %}
    </div>
    {% if caller %}<div class="flex items-center gap-2">{{ caller() }}</div>{% endif %}
  </header>
{% endmacro %}

{% macro empty_state(icon, title, body=None) %}
  <div class="text-center py-16">
    <i data-lucide="{{ icon }}" class="w-12 h-12 mx-auto text-disabled"></i>
    <h3 class="font-display text-lg font-semibold text-text mt-4">{{ title }}</h3>
    {% if body %}<p class="text-mute mt-2">{{ body }}</p>{% endif %}
    {% if caller %}<div class="mt-6">{{ caller() }}</div>{% endif %}
  </div>
{% endmacro %}

{% macro form_field(label, name, type="text", value="", required=False, help=None, error=None, placeholder="") %}
  <div class="mb-4">
    <label for="{{ name }}" class="block text-sm font-medium text-text mb-1.5">
      {{ label }}{% if required %} <span class="text-danger">*</span>{% endif %}
    </label>
    <input type="{{ type }}" id="{{ name }}" name="{{ name }}" value="{{ value }}"
           {% if required %}required{% endif %}
           {% if placeholder %}placeholder="{{ placeholder }}"{% endif %}
           class="input-soft w-full rounded-lg px-3 py-2.5 text-sm text-text">
    {% if help %}<p class="mt-1 text-xs text-mute">{{ help }}</p>{% endif %}
    {% if error %}<p class="mt-1 text-xs text-danger">{{ error }}</p>{% endif %}
  </div>
{% endmacro %}

{% macro form_textarea(label, name, value="", rows=4, required=False, help=None, error=None, placeholder="") %}
  <div class="mb-4">
    <label for="{{ name }}" class="block text-sm font-medium text-text mb-1.5">
      {{ label }}{% if required %} <span class="text-danger">*</span>{% endif %}
    </label>
    <textarea id="{{ name }}" name="{{ name }}" rows="{{ rows }}"
              {% if required %}required{% endif %}
              {% if placeholder %}placeholder="{{ placeholder }}"{% endif %}
              class="input-soft w-full rounded-lg px-3 py-2.5 text-sm text-text resize-none">{{ value }}</textarea>
    {% if help %}<p class="mt-1 text-xs text-mute">{{ help }}</p>{% endif %}
    {% if error %}<p class="mt-1 text-xs text-danger">{{ error }}</p>{% endif %}
  </div>
{% endmacro %}

{% macro form_select(label, name, options, selected="", required=False, help=None, error=None) %}
  {# options is a list of (value, label) tuples #}
  <div class="mb-4">
    <label for="{{ name }}" class="block text-sm font-medium text-text mb-1.5">
      {{ label }}{% if required %} <span class="text-danger">*</span>{% endif %}
    </label>
    <select id="{{ name }}" name="{{ name }}" {% if required %}required{% endif %}
            class="input-soft w-full rounded-lg px-3 py-2.5 text-sm text-text">
      {% for value, opt_label in options %}
        <option value="{{ value }}" {% if value == selected %}selected{% endif %}>{{ opt_label }}</option>
      {% endfor %}
    </select>
    {% if help %}<p class="mt-1 text-xs text-mute">{{ help }}</p>{% endif %}
    {% if error %}<p class="mt-1 text-xs text-danger">{{ error }}</p>{% endif %}
  </div>
{% endmacro %}

{% macro stat_tile(label, value, icon=None, tone="navy") %}
  {% set tone_bg = {"navy": "bg-navy-soft", "cream": "bg-cream", "white": "bg-white"}[tone] %}
  <div class="{{ tone_bg }} rounded-2xl p-5 border border-soft">
    <div class="flex items-center justify-between mb-2">
      <span class="text-xs uppercase tracking-wider text-mute font-semibold">{{ label }}</span>
      {% if icon %}<i data-lucide="{{ icon }}" class="w-4 h-4 text-navy"></i>{% endif %}
    </div>
    <div class="font-display text-3xl font-bold text-text">{{ value }}</div>
  </div>
{% endmacro %}

{% macro section_heading(label) %}
  <h2 class="text-xs uppercase tracking-wider text-mute font-semibold mb-3">{{ label }}</h2>
{% endmacro %}

{% macro table_wrapper(class="") %}
  <div class="bg-white rounded-2xl border border-soft overflow-hidden {{ class }}">
    <div class="overflow-x-auto">
      {{ caller() }}
    </div>
  </div>
{% endmacro %}
```

- [ ] **Step 2: Verify the file is syntactically valid Jinja**

Visit http://localhost:8001/ — if the file has a syntax error, **all** templates that extend `base.html` will fail. So a render of the dashboard at this stage proves nothing is broken just by adding the file (which isn't yet imported anywhere).

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```
Open http://localhost:8001/client/dashboard. Should render normally.

### Task 1.6: Run the test suite and commit PR 1

**Files:**
- None (tests + commit)

- [ ] **Step 1: Run pytest**

```bash
cd /Users/louije/Development/gip/traiteurs-style-refactor
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
```
Expected: all tests pass.

- [ ] **Step 2: Sweep through the sentinel pages side-by-side**

Open each page at port 8000 (pre) and port 8001 (post) in two browser windows side by side. Verify visual identity for each:

- `/`
- `/auth/login`
- `/auth/signup`
- `/client/dashboard` (alice)
- `/client/requests/new`
- `/client/requests/<some-id>` (open one)
- `/client/orders/<some-id>` (open one)
- `/caterer/dashboard`
- `/caterer/quotes/<some-id>` (open quote editor)
- `/admin/qualification`
- `/this-does-not-exist` (404)

Any visible difference = stop and investigate.

- [ ] **Step 3: Commit Phase 1**

```bash
cd /Users/louije/Development/gip/traiteurs-style-refactor
git add static/css/app.css static/css/tailwind.css templates/base.html templates/components/ui.html
git commit -m "refactor(css): consolidate brand tokens, add semantic utilities and ui macros"
```

- [ ] **Step 4: Push and (optionally) open PR 1**

```bash
git push -u origin refactor/style-tokens-foundations
```
Open a PR against `dev`. Title: `refactor(css): brand tokens, semantic utilities, ui macros (foundations)`. Body should reference the spec and explain that this PR is additive (no template adoption yet).

---

## Phase 2 — PR 2: Template sweep

After PR 1 merges to `dev`, branch from updated `dev` for the sweep.

### Task 2.0: Branch and refresh worktrees

**Files:**
- New branch `refactor/style-tokens-sweep` in the `traiteurs-style-refactor` worktree.

- [ ] **Step 1: In the original checkout, fetch updated `dev`**

```bash
cd /Users/louije/Development/gip/traiteurs
git checkout dev
git pull
```

- [ ] **Step 2: In the refactor worktree, create the sweep branch from updated `dev`**

```bash
cd /Users/louije/Development/gip/traiteurs-style-refactor
git fetch origin
git checkout -b refactor/style-tokens-sweep origin/dev
```

- [ ] **Step 3: Restart both containers so both pick up the merged baseline**

```bash
cd /Users/louije/Development/gip/traiteurs && COMPOSE_PROJECT_NAME=traiteurs-pre docker compose restart app
cd /Users/louije/Development/gip/traiteurs-style-refactor && COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Now port 8000 and port 8001 are both at the post-PR-1 baseline. They should look identical. From here on, every change to the refactor worktree will diverge port 8001's appearance — the goal is "no perceptible diff" per area.

### Task 2.1: Sweep `templates/auth/` (login, signup)

**Files:**
- Modify: `templates/auth/login.html`
- Modify: `templates/auth/signup.html`

**Combined inline `style="…"` count:** ~20 across both files.

- [ ] **Step 1: Apply the replacement table mechanically to `templates/auth/login.html`**

Open the file. For each `style="…"` attribute, look it up in the replacement table at the top of this plan. Apply the swap: delete the `style="…"` attribute, append the replacement class(es) to the existing `class="…"` attribute on the same element.

Examples expected in this file:
- `style="color: #6B7280"` → drop, add `text-mute` to class.
- `style="color: #1A1A1A"` → drop, add `text-text` to class.
- `style="color: #C4714A;"` → drop, add `text-coral` to class.

If a tag has no `class=""` attribute yet, add one.

- [ ] **Step 2: Same sweep for `templates/auth/signup.html`**

Same mechanical replacement.

- [ ] **Step 3: Verify no inline color/background hex literal remains in the two files**

```bash
grep -E 'style="[^"]*#' templates/auth/login.html templates/auth/signup.html
```
Expected: zero output. If any line returns, address it (likely a one-off not in the table — handle case-by-case).

- [ ] **Step 4: Run pytest**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
```
Expected: pass.

- [ ] **Step 5: Restart container and visual diff**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Open http://localhost:8000/auth/login next to http://localhost:8001/auth/login. Compare. Same for `/auth/signup`. Toggle between client/caterer tabs in signup. Must look identical to baseline screenshots and to port 8000.

- [ ] **Step 6: Commit**

```bash
git add templates/auth/login.html templates/auth/signup.html
git commit -m "refactor(templates): inline-style sweep — auth pages"
```

### Task 2.2: Sweep `templates/landing.html` and `templates/errors/`

**Files:**
- Modify: `templates/landing.html` (~63 styles)
- Modify: `templates/errors/404.html` (~8 styles)
- Modify: `templates/errors/500.html` (~8 styles)

- [ ] **Step 1: Sweep `templates/landing.html`**

Apply the replacement table. Notable special cases in this file:
- `style="padding: 54px 24px 48px; max-width: 1020px; margin: 0 auto;"` (~14 occurrences for content frames). Pragmatic call: keep as inline for now (one-off layout, no obvious utility group). If it's repeated in *other* files, then add `.frame-landing { padding: 54px 24px 48px; max-width: 1020px; margin: 0 auto; }` to `app.css`. Decide based on count after sweep — for now, leave inline and note in commit.
- `style="background: rgba(255,255,255,0.12);"` and `style="color: rgba(255,255,255,0.6);"` — these are translucent overlays on the dark hero. No existing utility. Add `.text-white-60 { color: rgba(255,255,255,0.6); }` and `.bg-white-12 { background-color: rgba(255,255,255,0.12); }` to `app.css` brand-utilities block; use them.

- [ ] **Step 2: Sweep `templates/errors/404.html`**

Replace `style="max-width:520px;margin:80px auto;text-align:center;padding:32px"` with `class="max-w-lg mx-auto my-20 text-center p-8"` (verify each utility exists in `tailwind.css`; `max-w-lg`, `mx-auto`, `my-20` may need to be present — `my-20` is `margin-top:5rem;margin-bottom:5rem` ≈ 80px; close enough algebraically).

Replace the inline-styled CTA button with `class="inline-block bg-navy text-white px-5 py-2.5 rounded-full font-bold text-sm"`.

Apply the table for any other inline styles.

- [ ] **Step 3: Same for `templates/errors/500.html`**

- [ ] **Step 4: Verify and pytest**

```bash
grep -rE 'style="[^"]*#' templates/landing.html templates/errors/
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
```
Expected: grep returns nothing or only documented exceptions; pytest passes.

- [ ] **Step 5: Visual diff**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Compare port 8000 vs 8001 for `/`, `/this-does-not-exist`, and any URL that triggers 500 (or just diff the file render manually).

- [ ] **Step 6: Commit**

```bash
git add templates/landing.html templates/errors/ static/css/app.css
git commit -m "refactor(templates): inline-style sweep — landing and errors"
```

### Task 2.3: Sweep `templates/client/` (top-level)

**Files:**
- Modify: `templates/client/dashboard.html` (~30 styles)
- Modify: `templates/client/profile.html` (~10)
- Modify: `templates/client/team.html` (~68)
- Modify: `templates/client/search.html` (~30)
- Modify: `templates/client/settings.html` (~18)
- Modify: `templates/client/caterer_detail.html` (~28)

- [ ] **Step 1: Apply replacement table to each file**

Standard mechanical sweep per the table. For files with high counts (`team.html`, `search.html`), be especially careful with multi-property style attributes.

- [ ] **Step 2: Look for macro adoption opportunities**

In each file, look for repeated patterns matching the new macros:
- A `<div class="bg-white rounded-2xl border …">` block → can become `{% call card() %}…{% endcall %}` (if its contents fit). Don't force-fit.
- Page-top `<h1>` + subtitle + (optional) action button → can become `{{ page_header(...) }}`.
- "no items" empty placeholders → `{{ empty_state(...) }}`.
- `<form>` `<label>` + `<input>` blocks → can become `{{ form_field(...) }}`.

**Adopt at least one macro somewhere in the client/ sweep.** This validates the macros work end-to-end and gives the broader codebase a usage example. Don't overdo it — priority is inline-style elimination.

- [ ] **Step 3: Verify, test, commit per file or as a batch**

```bash
grep -rE 'style="[^"]*#' templates/client/dashboard.html templates/client/profile.html templates/client/team.html templates/client/search.html templates/client/settings.html templates/client/caterer_detail.html
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Visual diff at port 8001 vs port 8000:
- `/client/dashboard`
- `/client/profile`
- `/client/team` (admin role)
- `/client/search`
- `/client/settings`
- `/client/caterer/<some-id>`

- [ ] **Step 4: Commit**

```bash
git add templates/client/dashboard.html templates/client/profile.html templates/client/team.html templates/client/search.html templates/client/settings.html templates/client/caterer_detail.html
git commit -m "refactor(templates): inline-style sweep — client top-level pages"
```

### Task 2.4: Sweep `templates/client/requests/` and `templates/client/orders/` and `templates/client/messages/`

**Files:**
- Modify: `templates/client/requests/list.html` (~22)
- Modify: `templates/client/requests/new.html` (~166 — biggest file)
- Modify: `templates/client/requests/edit.html` (~136)
- Modify: `templates/client/requests/detail.html` (~84)
- Modify: `templates/client/orders/list.html` (~17)
- Modify: `templates/client/orders/detail.html` (~44)
- Modify: `templates/client/messages/list.html` (~16)
- Modify: `templates/client/messages/thread.html` (~13)

- [ ] **Step 1: Sweep `requests/new.html` and `requests/edit.html` first (largest)**

These two files share most of the wizard markup. Apply the table. Pay extra attention to:
- Wizard step radio cards using `has-[:checked]` — already covered by the legacy block in `app.css`, but you can also migrate them to the new `has-[:checked]:bg-navy` / `has-[:checked]:bg-navy-soft` names for cleanliness.
- `style="display: none;"` sections toggled by `wizard.js` — replace with `class="hidden"`. This is safe (see "Why JS-driven `.style.X = …` is out of scope" at the top).
- `style="accent-color: #1A3A52"` on radio/checkbox inputs → `accent-navy` class.
- The form fields are good macro adoption candidates, but don't force-fit if the existing markup has Stimulus/Alpine/data-action handlers that complicate it. Prefer inline-style elimination over macro adoption.

- [ ] **Step 2: Sweep `requests/list.html` and `requests/detail.html`**

- [ ] **Step 3: Sweep `orders/list.html` and `orders/detail.html`**

- [ ] **Step 4: Sweep `messages/list.html` and `messages/thread.html`**

- [ ] **Step 5: Verify, test, visual diff**

```bash
grep -rE 'style="[^"]*#' templates/client/requests templates/client/orders templates/client/messages
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Visual diff:
- `/client/requests` (list)
- `/client/requests/new` — step through ALL wizard steps to verify hidden-section toggling still works
- `/client/requests/<id>` (detail)
- `/client/requests/<id>/edit`
- `/client/orders` (list)
- `/client/orders/<id>` (detail)
- `/client/messages` (list)
- `/client/messages/<id>` (thread)

The wizard pages are the highest-risk file in the project. Test the wizard interactively at port 8001: select dietary preferences, toggle waitstaff, change radio selection, navigate forward and back.

- [ ] **Step 6: Commit**

```bash
git add templates/client/requests/ templates/client/orders/ templates/client/messages/
git commit -m "refactor(templates): inline-style sweep — client requests, orders, messages"
```

### Task 2.5: Sweep `templates/caterer/`

**Files:**
- Modify: `templates/caterer/dashboard.html` (~24)
- Modify: `templates/caterer/profile.html` (~24)
- Modify: `templates/caterer/stripe.html` (~28)
- Modify: `templates/caterer/quotes/editor.html` (~43)
- Modify: `templates/caterer/requests/list.html` (~15)
- Modify: `templates/caterer/requests/detail.html` (~50)
- Modify: `templates/caterer/orders/list.html` (~13)
- Modify: `templates/caterer/orders/detail.html` (~48)
- Modify: `templates/caterer/messages/list.html` (~12)
- Modify: `templates/caterer/messages/thread.html` (~10)

- [ ] **Step 1: Sweep all caterer templates per the replacement table**

- [ ] **Step 2: Verify and test**

```bash
grep -rE 'style="[^"]*#' templates/caterer/
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

- [ ] **Step 3: Visual diff at port 8001 vs port 8000 (logged in as caterer)**

Pages to check:
- `/caterer/dashboard`
- `/caterer/profile`
- `/caterer/stripe`
- `/caterer/quotes/<id>` (editor — interactive: add/remove lines, type values)
- `/caterer/requests` (list)
- `/caterer/requests/<id>` (detail)
- `/caterer/orders` (list)
- `/caterer/orders/<id>` (detail)
- `/caterer/messages` (list)
- `/caterer/messages/<id>` (thread)

- [ ] **Step 4: Commit**

```bash
git add templates/caterer/
git commit -m "refactor(templates): inline-style sweep — caterer pages"
```

### Task 2.6: Sweep `templates/admin/`

**Files:**
- Modify: `templates/admin/dashboard.html` (~38)
- Modify: `templates/admin/stats.html` (~27)
- Modify: `templates/admin/messages.html` (~19)
- Modify: `templates/admin/payments.html` (~41)
- Modify: `templates/admin/qualification/list.html` (~23)
- Modify: `templates/admin/qualification/detail.html` (~59)
- Modify: `templates/admin/companies/list.html` (~22)
- Modify: `templates/admin/companies/detail.html` (~38)
- Modify: `templates/admin/caterers/list.html` (~25)
- Modify: `templates/admin/caterers/detail.html` (~49)

- [ ] **Step 1: Sweep all admin templates**

Standard mechanical sweep. `qualification/detail.html` has unusual one-offs (e.g. `style="width:12px;height:12px"` color dots). Use `w-3 h-3` (added in Phase 1).

- [ ] **Step 2: Verify and test**

```bash
grep -rE 'style="[^"]*#' templates/admin/
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

- [ ] **Step 3: Visual diff at port 8001 vs port 8000 (logged in as super admin)**

- `/admin/dashboard`
- `/admin/stats`
- `/admin/messages`
- `/admin/payments`
- `/admin/qualification`
- `/admin/qualification/<id>`
- `/admin/companies`
- `/admin/companies/<id>`
- `/admin/caterers`
- `/admin/caterers/<id>`

- [ ] **Step 4: Commit**

```bash
git add templates/admin/
git commit -m "refactor(templates): inline-style sweep — admin pages"
```

### Task 2.7: Sweep `templates/components/`

**Files:**
- Modify: `templates/components/confirm_dialog.html` (~6)
- Modify: `templates/components/flash_messages.html` (~1)
- Modify: `templates/components/status_badge.html` (~1)
- Modify: `templates/components/structure_type_badge.html` (~2)

- [ ] **Step 1: Apply the replacement table**

Lowest-volume area. Mostly already on classes.

- [ ] **Step 2: Verify, test, visual diff**

```bash
grep -rE 'style="[^"]*#' templates/components/
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Visual diff for any flash message (e.g., log out and back in to trigger flash), confirm dialog (e.g., delete a request to trigger the dialog), status badges (visible on `/admin/qualification`), structure-type badges (visible on `/client/search`).

- [ ] **Step 3: Commit**

```bash
git add templates/components/
git commit -m "refactor(templates): inline-style sweep — shared components"
```

### Task 2.8: Final cleanup — delete the legacy block

**Files:**
- Modify: `static/css/app.css` (remove "Legacy custom — to remove" block)

- [ ] **Step 1: Confirm no template still references the legacy class names**

```bash
grep -rE 'class="[^"]*\b(text-dark|hover:bg-\[#F5F1E8\]|focus:border-\[#1A3A52\]|has-\[:checked\]:bg-\[#1A3A52\]|has-\[:checked\]:bg-\[#F0F4F7\]|has-\[:checked\]:bg-white|has-\[:checked\]:text-white)\b' templates/
```
Expected: no output. (If any matches, migrate them to the new names: `text-text`, `hover:bg-cream`, `focus:border-navy`, `has-[:checked]:bg-navy`, `has-[:checked]:bg-navy-soft`.)

- [ ] **Step 2: Delete the "Legacy custom — to remove" block from `app.css`**

Remove the entire block (the comment header and all 7 rules added in Task 1.3).

- [ ] **Step 3: Verify no visual regression**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose restart app
```

Spot-check the wizard radio cards (`/client/requests/new`), the sidebar hover (`/client/dashboard`), and any element previously reliant on `.text-dark` (likely the sidebar user name in `base.html` — already swept in Phase 1).

- [ ] **Step 4: Final grep — should return nothing**

```bash
grep -rE 'style="[^"]*#' templates/
grep -rE 'style="[^"]*color:|style="[^"]*background-color:|style="[^"]*border-color:' templates/
grep -rE "font-variation-settings" templates/
```
All three: zero output. (Any non-zero output is a missed case from the sweep — handle before final commit.)

- [ ] **Step 5: Run pytest one final time**

```bash
COMPOSE_PROJECT_NAME=traiteurs-post docker compose exec app pytest
```
Expected: all tests pass.

- [ ] **Step 6: Commit and push**

```bash
git add static/css/app.css
git commit -m "refactor(css): remove legacy custom rules now that all templates migrated"
git push -u origin refactor/style-tokens-sweep
```

- [ ] **Step 7: Open PR 2**

PR title: `refactor(templates): eliminate inline styles, adopt token-backed utilities`. Body should reference the spec, list the touched areas, and call out:
- Number of inline styles removed (~1,409 → 0).
- The 7 new macros and where each is used.
- Verification approach (algebraic equivalence + side-by-side dev envs + pytest).
- Known follow-ups out of scope: JS-driven inline styles in `wizard.js`/`signup.js`/`app.js`.

---

## Phase 3 — Tear-down

### Task 3.1: Stop both dev instances

**Files:**
- None.

- [ ] **Step 1: Stop both compose stacks**

```bash
cd /Users/louije/Development/gip/traiteurs && COMPOSE_PROJECT_NAME=traiteurs-pre docker compose down
cd /Users/louije/Development/gip/traiteurs-style-refactor && COMPOSE_PROJECT_NAME=traiteurs-post docker compose down
```

- [ ] **Step 2: Optionally remove the worktree once both PRs merge**

```bash
cd /Users/louije/Development/gip/traiteurs
git worktree remove ../traiteurs-style-refactor
git branch -D refactor/style-tokens-foundations refactor/style-tokens-sweep   # only after PRs merge
```

---

## Final success criteria (for verifying the whole refactor)

Run from the merged `dev` branch after both PRs land:

1. `grep -rE 'style="[^"]*#[0-9A-Fa-f]+' templates/` → 0 hits.
2. `grep -rE 'style="[^"]*color:|background-color:|border-color:' templates/` → 0 hits.
3. `grep -rE "font-variation-settings" templates/` → 0 hits.
4. `grep -rE '#[0-9A-Fa-f]{3,6}' static/css/app.css | grep -v ':root\|/\*' | wc -l` → effectively only inside `:root` and comments. Brand colors live in exactly one place.
5. `templates/components/ui.html` exists and is imported by at least one template per area.
6. `pytest` passes.
7. Pre/post side-by-side at port 8000 vs 8001 shows no perceptible visual difference for any sentinel page.

---

## Self-review notes

- **Spec coverage:** all 7 success criteria from the spec map to tasks (Phase 2.8 step 4 + the final criteria above).
- **No placeholders:** every step has the exact command/code/file path.
- **Type / name consistency:** macro names (`card`, `page_header`, `empty_state`, `form_field`, `form_textarea`, `form_select`, `stat_tile`, `section_heading`, `table_wrapper`) and class names (`text-text`, `text-mute`, `bg-cream`, `bg-navy`, …) are used consistently across Phase 1 definition and Phase 2 references.
- **Bite-size:** most tasks (Phase 0, Phase 1.1-1.5, Phase 2.0, Phase 2.7, Phase 2.8) are 5-15 minute units. Phase 2 sweep tasks (2.1, 2.2, 2.3-2.6) are larger (30-90 minutes each) because per-template inline-style replacement is repetitive but cohesive — splitting one template across multiple commits is more friction than it's worth.
- **Out-of-scope items recorded:** JS-driven inline styles in `static/js/*.js`, optional `frame-landing` extraction, sidebar width CSS variable.
