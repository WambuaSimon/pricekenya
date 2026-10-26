# Handoff: PriceKenya revamp (home, category, product)

## Overview
A visual revamp of pricekenya.co.ke covering the three highest-traffic templates: the
homepage, a category listing, and a product page. The goals were: remove the emerald
gradient hero and emoji iconography, remove em dashes from all copy, raise the whole
grey ramp to WCAG AA, and restructure the homepage around price gaps and price drops
rather than a flat "best deals" grid.

Nothing about the data model, routing, or scraping changes. This is a template and
CSS-level change to `app/templates/`.

## About the design files
`PriceKenya.dc.html` in this bundle is a **design reference written in HTML**, not
production code. It is a single file containing all three screens stacked vertically
so they can be compared side by side.

The target codebase is a **FastAPI + Jinja2 + Tailwind (CDN) + HTMX** app
(`WambuaSimon/pricekenya`, branch `main`). Implement this by editing the existing
Jinja templates and using Tailwind utility classes, following the patterns already in
`app/templates/`. Do **not** port the inline styles from the reference file verbatim,
and do not introduce React or a build step.

Concretely, the files to change:

| Screen in reference | Target files |
| --- | --- |
| `#1a` Home | `app/templates/home.html`, `app/templates/base.html`, `app/templates/partials/_product_grid.html` |
| `#1b` Category | `app/templates/category.html`, `app/templates/partials/_filters.html`, `app/templates/partials/_pagination.html`, `app/templates/partials/_sidebar_nav.html` |
| `#1c` Product | `app/templates/product.html` |

## Fidelity
**High fidelity.** Colors, type sizes, spacing, radii and hover states are final and
should be matched. The exception is data: see "Data honesty" below.

## Design tokens

Add these to a `tailwind.config` extension in `base.html` rather than hardcoding hexes
across templates.

### Colors
| Token | Hex | Use |
| --- | --- | --- |
| `ink` | `#101413` | Headings, primary text, prices |
| `body` | `#3D4441` | Body text, nav links |
| `muted` | `#5C6360` | Secondary copy, stat labels, disclaimers (6.2:1 on white) |
| `faint` | `#6B7370` | Smallest metadata: freshness stamps, facet counts, legal microcopy (4.7:1 on white) |
| `accent` | `#0F5132` | Cheapest price, primary buttons, active states |
| `accent-hover` | `#0B3E27` | Primary button hover |
| `accent-tint` | `#EAF1EC` | Cheapest-price panel, badge background, icon wells |
| `accent-ink` | `#3F6E56` | Text on `accent-tint` |
| `line` | `#E4E7E5` | Card and input borders |
| `line-soft` | `#EDEFEE` | Internal dividers, header rules |
| `line-row` | `#F1F3F2` | Table row dividers |
| `surface` | `#FCFDFC` | Sidebar, footer, nav strip |
| `surface-2` | `#F8FAF9` | Table headers |
| `field` | `#F4F6F5` | Idle search field |
| `tile` | `#F1F4F2` | Image fallback tile |
| `bar-idle` | `#D3DED7` | Price-history bars other than the latest |
| `dark-panel` | `#101413` | Alert CTA band |
| `dark-panel-line` | `#333A37` | Input border inside that band |
| `dark-panel-field` | `#1A1F1D` | Input fill inside that band |
| `dark-panel-muted` | `#A8AFAB` | Body copy inside that band |

Greys below `#6B7370` were deliberately eliminated. Do not reintroduce
`#8B938F`, `#9AA19D` or `#B9BFBC` — all three fail AA on white.

### Typography
Two families, loaded from Google Fonts:

- **Instrument Sans** (400/500/600/700) — everything except numbers
- **IBM Plex Mono** (400/500/600) — all prices, counts, dates, stat figures, and
  uppercase eyebrow labels. Always with `font-variant-numeric: tabular-nums` where
  figures stack in a column.

| Role | Size / weight / tracking |
| --- | --- |
| Hero h1 | 50px / 600 / -0.035em / line-height 1.04 |
| Product h1 | 36px / 600 / -0.03em |
| Category h1 | 34px / 600 / -0.03em |
| Section h2 | 24px / 600 / -0.025em |
| Sub-section h2 | 20–22px / 600 / -0.02em |
| Hero lede | 17px / 400 / line-height 1.55 |
| Body | 14.5–15.5px / 400–500 |
| Card title | 14.5–15.5px / 500 / line-height 1.35 |
| Secondary | 13–14px / 400 |
| Eyebrow label | 11.5–12px / 700 / 0.06em / uppercase |
| Microcopy | 12px / 400 / line-height 1.5 |
| Price, large | 32–34px / 600 mono |
| Price, card | 16–19px / 600 mono |
| Price, row | 17px / 600 mono |

Long paragraphs carry `text-wrap: pretty`; the hero h1 carries `text-wrap: balance`.

### Spacing, radii, motion
- Page gutter: 32px. Section bottom spacing: 44–52px.
- Card padding: 14–24px. Grid gaps: 12–14px.
- Radii: 12px page container, 11px cards, 9–10px buttons and inputs, 8px small
  controls, 7px nav pills, 4–6px badges, 99px pills and progress tracks.
- Control heights: 52px hero search, 48px primary product buttons, 44px inputs,
  42px sidebar apply, 40px header search, 38px table buttons, 36px header links.
- Transitions: `.16s ease` on `background`, `border-color`, `color`, `box-shadow`.
  Table row hover uses `.14s`. No transforms, no scale-on-hover.
- Card hover: `border-color` to `#C3CCC7` plus `box-shadow: 0 4px 14px rgba(16,20,19,.06)`.
- The only shadow besides that: the WhatsApp pill, `0 6px 18px rgba(15,81,50,.24)`.
- No gradients anywhere. This is deliberate — the gradient hero was the main thing
  being removed.

## Iconography
Emoji are gone. Replace `product_placeholder_icon()` and `cat.icon` usage with a
stroke-icon set: `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`,
`stroke-width="1.7"`, round caps and joins. Sizes: 21px in category tiles, 16–18px
inline, 15px in breadcrumbs and chevrons, 13–14px in badges.

Icons needed: search, bell, star, arrow-right, chevron-down, arrow-down, filter,
check, tag, external-link, moon, copy, chat, plus one per top-level category
(phones, computing, tv, audio, camera, appliances, gaming, power, home). The
reference file's logic block contains the exact path data for all of them.

Category icons sit in a 42px `accent-tint` well with 9px radius on the homepage
browse grid, and inline at 16px in the nav strip.

## Screens

### 1a — Home
Order of sections, top to bottom:

1. **Header** (14px/32px padding, 1px `line-soft` bottom rule): logo at 26px, search
   field flex-1, then Watchlist and Alerts text-plus-icon links, then a 36px square
   dark-mode toggle. The toggle must keep the existing pre-paint `localStorage` theme
   script in `base.html` — the revamp must not regress that setting.
2. **Category nav strip** on `surface`: icon-plus-label pills, hover fills `accent-tint`.
3. **Hero**, `1fr / 468px` grid, 44px gap, 56px top padding.
   - Left: a freshness pill (`accent-tint`, 6px accent dot, "54 shops checked 9 hours
     ago"), h1, lede, a 52px search field with a `Compare` button, and a row of four
     popular-query links.
   - Right: the head-to-head card. Header strip on `surface-2` reading "Widest gap
     today" with an "All 11 offers" link; then a 76px product thumb, title, shop count
     and a min-to-max price line; then one row per offer with a "Cheapest" badge on the
     first; then an `accent-tint` panel stating the saving in words.
4. **"Where the gap is biggest"** — 4-up card grid. Each card: category eyebrow, title,
   large accent saving figure, a 4px progress track whose fill is
   `(high - low) / high`, and the low and high figures at each end.
5. **"Dropped this week"** — 3-up rows. Each: 48px fallback tile, title, current price,
   struck-through previous price, and an `accent-tint` percentage badge with a
   down-arrow icon.
6. **"Browse every category"** — 3-up cards, icon well plus name plus product count.
7. **Alert CTA band** — `dark-panel`, 12px radius, headline plus lede on the left,
   email field and white `Set an alert` button on the right.
8. **WhatsApp pill**, right-aligned in normal flow above the footer, with its
   dismiss button. Keep the existing 7-day dismissal cookie behavior. It must not be
   `position: absolute` with a hardcoded offset — that overlapped content.
9. **Footer** — `2fr 1fr 1fr 1fr` grid: logo plus disclaimer, then Shop, Tools, About
   link columns.

### 1b — Category
Header and nav as 1a, then a breadcrumb row, then a title block with the lede on the
left and three stat figures on the right (Products, Shops, Comparable — the third in
accent). The "Compared" info-chip popover from the current `category.html` is replaced
by this always-visible third stat, so the delegated `[data-info-toggle]` handler can go.

Below: child-category pills, then a `252px / 1fr` grid.

- **Sidebar** (`surface`, 11px radius, sticky): "Filters" heading with a filter icon and
  a "Clear all" link, a max-price field, then one block per facet with checkbox rows
  carrying a right-aligned count in mono, then a checked "Only comparable products"
  toggle, then a full-width `Apply filters` button. Keep the existing GET-form,
  URL-driven filtering — no client JS.
- **Results**: a result count and a sort control on one row, then a 3-up product grid,
  then centered pagination.

Product cards: 4:3 image area with a 1px bottom rule, then title (39px min-height so
rows align), then price and shop count on one line, then "Save up to X" in accent when
the spread is non-zero.

### 1c — Product
Breadcrumb, then a `392px / 1fr` grid, 36px gap.

- **Left**: square image, then a single credit line ("Image from <merchant>, one of the
  11 shops listing this phone"). There is deliberately **no thumbnail strip** — the data
  model has one `image_url` per product, so a gallery would render as empty boxes.
- **Right**: brand and metadata line, h1, then a split panel — `accent-tint` cheapest
  block (32px accent price plus shop name) beside a narrower "Dearest" block. Then a
  `field` callout with a tag icon stating the spread in words. Then the action row:
  `Go to cheapest shop` (accent, flex-1), `Watch price` (outlined, bell icon), and a
  48px square star button. Then the share strip: "Send this to someone" plus
  `Share on WhatsApp` and `Copy link`, both wired to the existing handlers in
  `product.html`. Then the spec strip above a `line-soft` rule: render only the keys that are
  present, capped at 4, and omit the strip entirely below 2. Only 44% of products have
  four or more keys and 8% have none, so a fixed 4-up renders blank slots for the
  majority. The reference shows four because the A17 happens to have four.

Then:
- **Where to buy** table, `1fr 140px 120px 150px`. Header on `surface-2`. Each row: shop
  name with a "Cheapest" badge on the first, the merchant listing title truncated to one
  line, a mono freshness stamp, the price right-aligned, an "Extra cost" column showing
  `+N` against the cheapest, and a `Go to shop` button that inverts to accent on hover.
  A "Show N more shops" footer row when collapsed. Keep `rel="nofollow sponsored"`.
- **Price over 8 weeks**, one bar per week, heights proportional to the max, latest bar
  in accent and the rest `bar-idle`, date labels beneath. Eight bars, not thirteen:
  history starts 2026-07-02, so there are 54 days of data and a 90-day frame would render
  five empty slots that read as missing data. Title the section by the window the data
  actually covers, and derive the bar count from the range rather than hardcoding it —
  when history reaches 90 days the same code gives 13 bars. This replaces the canvas
  sparkline currently disabled behind `{% if false and history %}` in `product.html`.
  Feed it a best-price-per-week series, which is the reshape that comment asks for.
- **Tell me when it drops**, beside the chart: email field, a KSh-prefixed target-price
  field, accent submit, legal microcopy. Same HTMX POST to `/alerts`.
- **Reviews**: a dashed-border empty state (five outline stars, "No reviews yet", one
  line of explanation) beside the write-a-review card — rating stars, name, email,
  body textarea, then Pros and Cons side by side, submit, and the confirm-by-email
  note. Keep the existing HTMX POST to `/reviews`, the cumulative `fillStars` behavior,
  the "Email confirmed" and "Edited" badges, and the Report action on published reviews.
  The reference only shows the empty state because the A17 has no reviews.
- **Phones around this price**: 6-up compact cards.

Implementation note: the Pros/Cons grid must use `minmax(0,1fr) minmax(0,1fr)`, not
`1fr 1fr`. With `1fr` the columns floor at the inputs' min-content width and the row
overruns its card.

## Images
Keep the existing pattern from `_product_grid.html` exactly: a fallback layer behind,
the `<img>` over it, `referrerpolicy="no-referrer"`, and hide-on-error. One change:

1. The fallback is no longer an emoji. It is a `tile`-filled box with the brand name (or
   first initial in small slots) centered at `faint`, 14px, weight 600.
2. The truthy-`image_url` guard is already correct in `_product_grid.html:16`. No change.

Roughly 7% of merchant URLs 403 on hotlink per the audit comment in
`_product_grid.html` — phoneplacekenya.com among them. Worth proxying or caching
images server-side, at which point the fallback becomes rare rather than routine.

## Data honesty
Real, taken from the live site and the repo: all Samsung A17 offers, shops, listing
titles and check times; the homepage product names, prices and offer counts; the
category tree and slugs; the 8,612 product count.

Invented for layout purposes and **must be replaced with real queries**: every
price-drop percentage and was-price, the weekly history series, all facet counts, the
spec strip, and the max prices behind the gap cards for everything except the A17. The
category page's three stats are **not** placeholders — `product_count`,
`merchant_count` and `compared_count` are already computed in `categories.py:255-266`;
wire them straight through. The fetched pages only expose a min price and
an offer count, so anything requiring a maximum or a history is placeholder.

## Freshness claim
The hero pill now reads **"43 shops checked in the last 24 hours"**, and the body copy
says 43, not 54. The old "54 shops checked 9 hours ago" was wrong: `merchant_count`
counts merchants with any listing, including 11 deprecated ones whose data is 300–800
hours stale. The pill is the most prominent verifiable claim on a price-comparison site,
so it has to be true of the number beside it. Count merchants with
`last_checked_at >= now() - interval '24 hours'`. The same `merchant_count` feeds the
category page's **Shops** stat — fix it in one place and both become honest. If the 24h
figure moves off 43, the pill follows it; do not hardcode.

Deprecated merchants are excluded outright: no rows in **Where to buy**, and no
contribution to the min/max price range or the offer counts. A stale row makes the
spread look wider than a buyer can actually act on, which is the one number this site
exists to report. Excluding them may lower some offer counts — that is correct, and the
"11 shops list this phone" style strings must be computed after the exclusion, not
before.

## Responsive
The reference is a 1280px desktop frame only. Keep the app's mobile-first structure —
`md:`/`lg:` prefixes, the off-canvas sidebar, the mobile filter drawer — and collapse
as follows. Breakpoints are Tailwind defaults: `md` 768, `lg` 1024.

- Gutters: 32px at `lg`, 24px at `md`, 16px below.
- **Home hero** `1fr 468px` → single column below `lg`; the widest-gap panel moves
  below the search block, full width. Hero h1 50px → 38px → 30px.
- **Home card grids** 4-up → 2-up at `md` → 1-up below. The drops grid 3-up → 2-up →
  1-up. Category grid 3-up → 2-up → 1-up.
- **Category page** `252px 1fr` → the sidebar becomes the existing filter drawer below
  `lg`, triggered by a full-width "Filters" button above the grid. Product grid 3-up →
  2-up at `md` → 2-up below (not 1-up; the cards are compact enough and 1-up wastes
  the fold on the mobile traffic that dominates here).
- **Product page** `392px 1fr` → single column below `lg`, image first, then the price
  panel, then actions. The action row stays horizontal; the star button keeps its 48px
  square.
- **Where to buy** table `1fr 140px 120px 150px` → below `md` each row becomes a
  two-line stacked card: shop name and badge on line one, price and `Go to shop` on
  line two, listing title and freshness stamp beneath at `ink-2`. Drop the "Extra cost"
  column below `md`; it is the least load-bearing of the four. Do not horizontally
  scroll the table.
- **Chart** keeps its bar count; bars just get narrower. Below `md` the alert form
  moves beneath the chart rather than beside it.
- Every tap target is 44px minimum below `md`, including the facet checkboxes, which
  are 16px visually — pad the label, not the box.

## Focus and motion
Hover is specified precisely, so focus must be too. Every interactive element gets:

    :focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }

`--focus` is `#0F5132` on light and `#7FE3B0` on dark. Never remove the outline
without replacing it, and never use `:focus` alone — mouse users should not see rings.
On the accent-filled buttons the ring sits outside the fill, so the offset matters. Keep
the existing `.16s ease` transitions but wrap them:

    @media (prefers-reduced-motion: reduce) { * { transition-duration: 0.01ms !important; } }

## Degraded states
The reference shows fully populated screens. These are the fallbacks:

- **Where the gap is biggest** — needs 4 products with a real max price. With 2 or 3,
  render what exists and let the grid short-fill; the cards are equal-width so a 2-up
  row reads as deliberate. With fewer than 2, omit the whole section including the
  heading. Never pad with placeholder cards.
- **Dropped this week** — in a flat week, omit the section rather than showing zero-drop
  rows. A "no drops this week" empty state is a worse answer than silence on a homepage.
- **Head-to-head panel** — when no product has enough offers, keep the existing fallback
  at `home.html:94` and restyle it to the `field` callout: one line of `ink-2` text
  inside a `surface-2` box with the tag icon, no border-radius change.
- The four popular-query links in the hero are hardcoded strings in the reference. Make
  them data-driven off the top search queries if that is cheap, otherwise leave them
  hardcoded and keep them to four.

## Dark mode
Derived, not previously approved — review the **2a** board in the reference before
building. It is the green-tinted ramp: the accent survives into dark instead of the
whole UI going neutral charcoal.

| Token | Light | Dark |
| --- | --- | --- |
| `canvas` | `#E9EBEA` | `#08130D` |
| `surface` | `#FFFFFF` | `#0F1F16` |
| `surface-2` | `#FCFDFC` | `#14281C` |
| `tile` | `#F1F4F2` | `#142A1E` |
| `line` | `#E4E7E5` | `#1E3A2A` |
| `line-soft` | `#EDEFEE` | `#17301F` |
| `ink` | `#101413` | `#E8F2EB` |
| `ink-2` | `#3D4441` | `#A8BFB1` |
| `faint` | `#5C6360` | `#7B968A` |
| `accent` | `#0F5132` | `#5CCF94` |
| `accent-ink` | `#FFFFFF` | `#08130D` |
| `accent-tint` | `#EAF1EC` | `#143026` |
| `bar-idle` | `#D3DED7` | `#264934` |
| `focus` | `#0F5132` | `#7FE3B0` |

Notes that matter more than the hexes:

- Text on the dark accent flips to `accent-ink`, not white. `#5CCF94` is light enough
  that white on it fails; near-black on it passes comfortably.
- Do not carry the light box-shadows into dark. Elevation is the `line` border only;
  shadows on a dark canvas read as smudge. The card hover that adds a shadow in light
  should brighten the border in dark instead.
- Product images sit on `tile`, not `surface`. Merchant cutouts are mostly white
  backgrounds, so they will look like bright rectangles either way; the darker tile at
  least contains them. Do not filter or dim the images.
- Preserve the pre-paint theme script exactly as it is. It runs before first paint to
  avoid a flash; anything you add to it reintroduces the flash.
- The toggle stays on all three screens.

## Assets
`logo.svg` — copied unchanged from `app/static/logo.svg` in the repo. Reference the
existing static file; it is included here only so the reference renders standalone.

Fonts are **self-hosted**: Instrument Sans and IBM Plex Mono, latin subset, woff2 only,
served from `app/static/fonts/`. No Google Fonts request, no preconnect, no
render-blocking third party — the repo currently loads none and it stays that way.
Declare each with `@font-face` and `font-display: swap`, and preload only the two
weights above the fold (sans 600 and mono 600). The reference file still links Google
Fonts so it renders standalone; that link does not go into the app.

Historical note — the Google Fonts option below was declined:
render time, self-host both families and drop the `<link>` tags.

## Files in this bundle
- `CLAUDE_CODE_PROMPT.md` — paste-ready prompt for Claude Code, including model routing.
  Start here.
- `PriceKenya.dc.html` — all three screens. Open it in a browser. The logic block at
  the bottom holds the icon path data and the sample data arrays.
- `logo.svg` — the brand mark.
- `screenshots/1a-home.png`, `screenshots/1b-category.png`,
  `screenshots/1c-product.png` — full-length captures at 2x, for reference only.
  Where a screenshot and the HTML disagree, the HTML is correct.
