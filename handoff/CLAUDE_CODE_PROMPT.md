# Prompt for Claude Code

Copy everything below the line into Claude Code as your first message, from the root of
your `pricekenya` checkout, with this handoff folder available (see "Before you start").

---

## Before you start

1. Copy this handoff folder into the repo root as `handoff/` (or note wherever it lives
   and adjust the paths below).
2. Open `handoff/PriceKenya.dc.html` in a browser and keep it open. You will refer to it
   constantly.
3. Start on **Sonnet 5** (`/model sonnet`). Model routing per phase is at the bottom.

---

## The prompt

I'm applying a visual revamp to this codebase. The full spec is in `handoff/README.md` —
read it completely before writing any code, along with `handoff/PriceKenya.dc.html`,
which is the visual reference containing all three screens.

**Read these first, before proposing anything:**

- `handoff/README.md` — tokens, per-screen specs, and the screen-to-file mapping
- `handoff/PriceKenya.dc.html` — the design reference
- `app/templates/base.html` — existing chrome, theme script, Tailwind setup
- `app/templates/home.html`, `category.html`, `product.html`
- `app/templates/partials/_product_grid.html`, `_filters.html`, `_pagination.html`,
  `_sidebar_nav.html`

### What this is

A template and CSS-level revamp of the three highest-traffic pages. The data model,
routes, and scrapers do not change. The goals were: remove the gradient hero and emoji
iconography, remove em dashes from all copy, raise the entire grey ramp to WCAG AA, and
restructure the homepage around price gaps and price drops instead of a flat deals grid.

### Hard constraints

1. **The reference file is not production code.** It is a single HTML file with inline
   styles, written to be viewed standalone. This codebase is FastAPI + Jinja2 +
   Tailwind (CDN) + HTMX. Implement the design by editing the existing Jinja templates
   with Tailwind utility classes, following the conventions already in
   `app/templates/`. Do not copy the inline styles across. Do not introduce React, a
   bundler, or a build step.

2. **Tokens go in one place.** Add the color scale from the README as a
   `tailwind.config` extension in `base.html`. Do not scatter raw hex values through
   templates.

3. **Preserve all existing behavior.** Specifically: the pre-paint `localStorage` theme
   script, the dark-mode toggle, the WhatsApp pill's 7-day dismissal cookie, the
   URL-driven GET-form filtering (no client-side filter JS), every HTMX endpoint
   (`/alerts`, `/reviews`), the cumulative `fillStars` behavior, the "Email confirmed"
   and "Edited" review badges, the Report action, and `rel="nofollow sponsored"` on all
   outbound merchant links. If a redesigned element has no obvious home for existing
   behavior, ask me rather than dropping it.

4. **Accessibility is not negotiable.** Every grey below `#6B7370` was deliberately
   removed. Do not reintroduce `#8B938F`, `#9AA19D`, or `#B9BFBC` — all three fail AA
   on white. Secondary copy is `#5C6360`, the faintest tier is `#6B7370`.

5. **No gradients anywhere.** Removing the gradient hero was the single biggest reason
   for this revamp.

6. **Don't rewrite copy.** The strings in the reference are final, including the absence
   of em dashes. If you need new copy for something the reference doesn't cover, write
   it plainly and flag it to me.

### Two specific bugs not to reintroduce

- The Pros/Cons grid on the review form must be `minmax(0,1fr) minmax(0,1fr)`, not
  `1fr 1fr`. With `1fr` the columns floor at the inputs' min-content width and the row
  overruns its card by about 70px.
- The WhatsApp pill must sit in normal document flow above the footer. An earlier
  version used `position: absolute` with hardcoded `bottom` offsets and it landed on
  top of content when section heights changed.

### Images

Keep the existing fallback pattern from `_product_grid.html` exactly — fallback layer
behind, `<img>` over it, `referrerpolicy="no-referrer"`, hide-on-error. Two changes:
the fallback is a `tile`-filled box with the brand name (or first initial in small
slots) at `faint`, not an emoji; and render the `<img>` only when `product.image_url`
is truthy, because a null src paints broken-image alt text over the fallback.

Roughly 7% of merchant image URLs 403 on hotlink per the audit comment in that file.
Don't fix that as part of this work, but tell me at the end whether you think a
server-side image proxy is worth a follow-up.

### Data honesty

The README has a section listing exactly which numbers in the reference are real and
which are placeholders I invented for layout. **Do not ship the placeholders.** For each
one, either write the real query or leave the section out and tell me. This applies to
all price-drop percentages and was-prices, the weekly history series, every facet count,
the product spec strip, and the max prices behind the gap cards for everything except the
Samsung A17. The category page's three stats are real — `product_count`,
`merchant_count` and `compared_count` already exist in `categories.py:255-266`.

The weekly price chart replaces the canvas sparkline currently dead behind
`{% if false and history %}` in `product.html`. It needs a best-price-per-week series,
which is the reshape that code comment is asking for. Derive the bar count from the
actual history range, not a fixed 13 — today that is 8 weeks. Treat that as a real task, not a
copy-paste.

### How I want you to work

Decisions already made — do not relitigate them:

- Fonts are self-hosted woff2, latin subset, in `app/static/fonts/`. No Google Fonts
  request. The reference file's Google link is for standalone rendering only.
- Dark mode ships with these three screens using the token table in the README's
  **Dark mode** section. Preserve the pre-paint theme script byte for byte.
- The hero freshness pill says "43 shops checked in the last 24 hours". The old 54 was
  wrong — `merchant_count` includes 11 deprecated merchants with 300–800 hour old data.
  Fix the count at the query, and note the same value feeds the category page's Shops
  stat. Deprecated merchants are excluded from the offers table and from the price range.
- This handoff directory lives outside the repo. Do not commit it, do not add it to
  `.gitignore`, do not reference its path in any file you write.
- `watchlist.html` also calls `product_placeholder_icon()` and is out of scope. It keeps
  its emoji fallbacks for now. Do not touch it and do not change the shared helper's
  signature in a way that would break it — add the icon set alongside, don't replace.
- Responsive collapse rules, `:focus-visible`, `prefers-reduced-motion`, and the
  degraded-state fallbacks are all specified in the README. Follow them; they are not
  yours to invent.

Start by reading everything listed above, then give me a short implementation plan:
which files you'll touch per screen, what you'll add to the Tailwind config, which
placeholder numbers need queries, and anything in the spec that conflicts with what's
already in the codebase. **Wait for me to approve the plan before writing code.**

Then work one screen at a time in this order: home, category, product. After each
screen, stop and tell me what changed and what you couldn't do. Don't start the next
screen until I say go.

Prefer editing existing templates over creating new ones. Don't reformat or "tidy" code
you weren't asked to change — keep the diff reviewable. If the spec and the existing
code disagree about something behavioral, ask; if they disagree about something purely
visual, the spec wins.

Where a screenshot in `handoff/screenshots/` and the HTML reference disagree, the HTML
is correct.

---

## Model routing

**Sonnet 5** for the bulk of it — the three screens, the Tailwind config, the icon
swap. It's the daily driver for Claude Code work and this is well-specified execution:
the spec has the exact hexes, sizes, and file mapping, so the task is careful
transcription rather than architectural reasoning.

Switch to **Opus 5** (`/model opus`) for the parts that need judgment:

- reshaping the price history into a best-price-per-week series
- writing the queries behind the gap, drop, and facet-count figures
- any point where the spec and the existing code genuinely conflict

Skip **Fable 5**. On Max plans it's capped at 50% of weekly usage and a session weighs
roughly double an Opus one. It buys nothing on Jinja templates.

If you're on Pro, Sonnet 5 is your default anyway and Opus access is limited — in that
case do the whole visual pass on Sonnet, and save your Opus budget for the data-query
phase at the end.
