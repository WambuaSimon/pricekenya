# PriceKenya — Operations log (PRIVATE, not tracked in git)

Moved out of the public CONTEXT.md on 2026-08-24.

This file is the merchant-by-merchant record of scraper outages: which
bot-mitigation each merchant runs, exactly what defeats it, and which
merchants successfully locked us out. Published alongside the merchant
names and base URLs in `scrapers/config/`, it is a step-by-step guide for
any merchant who wants to block us — and it is what got the repo picked
up by proxy-vendor lead-gen scraping GitHub for "residential proxy".

`.gitignore` excludes it. Keep it that way. If this needs to be shared or
backed up, put it in a PRIVATE repo, not this one.

Two caveats worth remembering:

  - Removing it from HEAD does NOT remove it from git history. Every
    section below is still readable in the public commit log unless that
    history is rewritten (`git filter-repo`, force-push, and every clone
    re-cloned). See the PR that moved this file.
  - This file is not the only copy of the sensitive material. The
    per-merchant comments in `scrapers/config/wc_merchants.py` explain the
    same escalations and fixes inline, and those are still public.

---

## 8. First live-scrape learnings (2026-07-01)

Ran `python -m scrapers.ingest jumia-phones` against live Jumia for the first time. Results:

- **No blocks.** 3 pages fetched clean with the polite httpx client + 2s delay.
- **Selectors held.** `article.prd`, `.name`, `.prc`, `img.img` all still work.
- **Images render.** Jumia CDN URLs embed directly with no hotlink protection.
- **63 unique phones ingested.** Merged into 64 products (5 pre-existing from seed + 59 new).
- **Matcher parse rate: 62/63 (~98%).** One title (`"...Battery 2.0+12 MONTHS WARRANTY"`) matched the storage-pair regex on `"0+12"` and produced a phantom `realme|c100i|12` product. Fixed with a `(?<!\.)` lookbehind + `[16..4096]GB` storage-range sanity check. Regression test locked in.
- **Cross-merchant merges: 5.** All from seed; no scraped Jumia phone happens to match a seed model. Validates that we can't demonstrate the core "compare prices" value prop with one merchant — need Kilimall next.

**Kilimall scraper landed 2026-07-01:** Category pages return 500, but `/search?q=smartphone` server-renders 36 clean cards/page as a Nuxt app. 60 listings ingested. **13 products now carry both Jumia + Kilimall offers** — the core "compare prices" value prop is now demonstrable on real data. Biggest observed gap: Samsung A07 4/128GB shows 38% price difference (likely bad Kilimall data — motivates the counterfeit/lowball flag from the v1 roadmap). Known gap: Kilimall images are lazy-loaded and not in initial HTML; listings from Kilimall show no thumbnail until we either parse `window.__NUXT__` state or hit product detail pages.

## 8b. Merchant expansion sprint (2026-07-05 → 2026-07-06)

Grew merchant coverage from 2 → 12 across two sessions. All numbers are local sqlite listing counts after the matcher runs.

| # | Merchant | Slug | Scraper approach | Listings | Session added |
|---|---|---|---|---|---|
| 1 | Jumia Kenya | `jumia-ke` | httpx + selectolax, category pages | 1024 | prior |
| 2 | Kilimall Kenya | `kilimall-ke` | httpx + Nuxt hydration parse, `/search?q=` | 774 | prior |
| 3 | Naivas | `naivas-ke` | curl_cffi + Livewire `wire:snapshot` regex | 121 | 2026-07-05 |
| 4 | Phone Place Kenya | `phoneplace-ke` | curl_cffi + WooCommerce `.product-wrapper` | 163 | 2026-07-05 |
| 5 | Phones Store Kenya | `phonesstore-ke` | httpx + same WooCommerce theme (no CF wall) | 37 | 2026-07-05 |
| 6 | Quickmart | `quickmart-ke` | curl_cffi + Growcer PHP, `/4301` bootstrap cookie | 165 | 2026-07-06 |
| 7 | Carrefour Kenya | `carrefour-ke` | curl_cffi + Next.js RSC escaped-JSON parse | 135 | 2026-07-06 |
| 8 | Xiaomi Kenya | `xiaomi-ke` | curl_cffi + custom WooCommerce, `product_cat-*` routing | 48 | 2026-07-06 |

**Multi-offer products across the site: 280 → 414 (+134 = +48%).** That's the number of Product rows carrying offers from >1 merchant — the core "compare prices" story. Two products now show side-by-side offers from 4 merchants each (e.g. Redmi 15C: Jumia + Kilimall + Quickmart + Xiaomi Kenya).

**Key infra added:** `curl_cffi>=0.7` + a new `CffiPoliteClient` in `scrapers/common/base.py`. Chrome TLS impersonation defeats Cloudflare (Naivas, Phone Place) and Akamai (Carrefour) cleanly; ~2s polite delay retained. Plain `httpx.PoliteClient` still fine for unshielded merchants (Kilimall, Phones Store).

**Site-specific quirks worth remembering:**
- **QuickMart** uses `?page-N` (hyphen, not `=`) — Growcer/Yo!Grocery pagination. Standard `?page=2` silently re-serves page 1 (cost 30 minutes to discover).
- **Carrefour** is a Next.js SPA; parse the escaped-JSON RSC payload (`\"productId\":`), not the visual HTML — prices come as integers, no comma parsing.
- **Xiaomi Kenya** (`xiaomistores.co.ke`) has flat product URLs (`/redmi-15c/`), NOT `/product/<slug>/` like most WooCommerce sites. Category routing via `product_cat-<slug>` classes on the `<li>`, specificity-ordered (model-family first, generic last).
- **Naivas** encodes product cards in Livewire `wire:snapshot` markers; anchor tags span multiple lines so regex needs `re.DOTALL`.

**Blocked/deferred:**
- **mi.com/ke** stays an SPA shell (no KSh in HTML shell); **xiaomi-store.co.ke** stays 403-blocked even with Chrome impersonation. `xiaomistores.co.ke` is the cleanest Xiaomi source available.
- **Carrefour phones/tablets/wearables** live under a *separate* top-level category tree (not `NFKEN4000000`) — v0 only covers the Electronics & Appliances parent. Tree ID capture needed.
- Older merchant scrapers (Hotpoint, Ramtons, Avechi, iStore, Gadget World, Masoko) have code but 0 rows in local sqlite. May be producing on prod Neon via the GitHub Actions cron — not investigated yet.

## 8c. Frontend polish (2026-07-06)

- **Dark mode**: Tailwind CDN configured with `darkMode: 'class'`. Small no-FOUC boot script reads `localStorage.theme` and system preference before first paint. Sun/moon toggle in header persists the choice. All templates got `dark:` variants (backgrounds, borders, text hierarchy, price-history canvas stroke).

## 8d. Tester feedback pass (2026-07-07)

Round of fixes from 5 testing buddies. Shipped:

- **Search empty-state**: clearing the search box now returns the multi-offer showcase (same query as home page), not a blank grid. `app/routes/pages.py` — with LIKE-arg escaping added while I was there.
- **"Best price" badge**: cheapest offer on `/p/*` now gets a green tint + `Best price` chip. Offers were already sorted `price_kes ASC` in `products.py`, so it's purely a template change (`{% if loop.first %}`).
- **Cookie-based watchlist**: HMAC-signed `watchlist` cookie stores the alert IDs a browser has created (HttpOnly, Secure, SameSite=Lax, 1yr). New `GET /watchlist` route + template lists the tracked products. Sidebar and header gain a Watchlist link only when the cookie is present. Unsubscribe endpoint prunes the id from the cookie too. Signing key = `SECRET_KEY` (shared with unsubscribe tokens). Privacy Policy §6 updated to disclose it.
- **Product description**: added `Product.description TEXT NULL` (migration `add_product_description.py`), rendered on `/p/*` as "About this product", included in Product JSON-LD when present. Scrapers still to be updated per-merchant.
- **Left sidebar nav** (mobile UX): horizontal scroll-to-hidden-items nav replaced with off-canvas sidebar. Desktop (md+) shows a persistent 224px column on the left; mobile shows a hamburger in the header that toggles a slide-in drawer with backdrop + ESC/click-out to close. `_category_nav.html` deleted, `_sidebar_nav.html` added. Outer wrapper widened to `max-w-7xl` to make room for the column.

Deferred (v2 territory): visitor reviews, merchant self-serve JSON/XML feed, home page grouped-by-category top-3 layout.

## 8f. Solar & power-backup MVP (2026-07-07)

Added `power-energy` top-level category with 3 leaves: `inverters`, `solar-panels`, `solar-batteries`. Kenya-specific opportunity (unreliable grid + off-grid rural + boda charging), high AOV, brand+model canonical.

- **Matcher** (`matching/solar_energy.py`) — one module, three `expected_type` variants (`inverter` / `solar-panel` / `solar-battery`). Canonical key formats:
  - `inverter:<brand>:<watts>[:<topology>]` — watts required, topology (hybrid / pure-sine / modified / off-grid / grid-tie) optional.
  - `panel:<brand>:<watts>[:<cell_type>]` — watts required, cell type (mono / poly / bifacial / thin-film) optional.
  - `battery:<brand>:<capacity_ah>[:<chemistry>][:<voltage>v]` — at least one of {Ah, chemistry} required.
  - Handles `kW`/`kVA`/`VA`/`W`/`watts` unit variants; rejects solar "kits" from all three leaves (kits are their own product category, not to be confused with pure panel/battery/inverter listings).
  - Rejects the usual accessory noise (cables, connectors, brackets, MC4 connectors, car/AA/watch batteries, power banks).
- **Scrapers**:
  - **Jumia**: `/inverters/` (real category) + `/solar-panels/` (real category) + `/catalog/?q=solar+battery` / `?q=lithium+battery` / `?q=deep+cycle+battery` searches (no dedicated battery category).
  - **Kilimall**: search-based (`solar inverter`, `pure sine wave inverter`, `hybrid inverter`, `solar panel`, `monocrystalline solar panel`, `solar battery`, `lithium battery`, `deep cycle battery`).
  - **Hotpoint**: scaffolded (`fetch_inverters` / `fetch_solar_panels` / `fetch_solar_batteries`) but disabled because their /solar-*/ URLs return 200 with empty categories as of 2026-07-07 — site no longer surfaces solar in nav. One-line flip in `LEAF_TO_URLS` to re-enable when they restock.
- **Ingest wiring**: `run_jumia_inverters` / `run_kilimall_inverters` etc.; combined `all-inverters` / `all-solar-panels` / `all-solar-batteries` targets (Jumia + Kilimall only for now). Added to `_run_all` and to the GH Actions `scrape.yml` matrix.
- **Frontend**: `power-energy` top-level got a ⚡ icon in `NAV_ICONS` so it shows in the sidebar as soon as any listing lands.
- **Dry-run parse rates** (40-listing samples): jumia-inverters 37 %, kilimall-inverters 30 %, jumia-panels 27 %, kilimall-panels 27 %, jumia-batteries 35 %, kilimall-batteries 37 %. Rejections are dominated by unknown brands (Kenyan-import OEMs), solar kits (correctly filtered), and products missing key specs. **Solarmax** dominates the Kenyan market and is well-covered.

Next: run scrapers against Neon via GH Actions, watch how many multi-offer products materialise, iterate matcher brand list from unmatched titles.

## 8e. MyBigOrder scraper (2026-07-07)

Added `scrapers/merchants/mybigorder.py` — Kenyan multi-vendor marketplace (mybigorder.com). Server-rendered PHP (Active eCommerce CMS template family). No Cloudflare, uses plain `PoliteClient`. Prices already in KSh.

- One URL per PriceKenya leaf: `phones`, `tablets`, `phone-tablet-accessories`, `laptops`, `tvs`, `cameras`, `audio`, `cooking` — set `category_slug` at fetch time.
- Two mixed appliance buckets (`large-appliances-txwkq`, `small-appliances-zf9qd`) — route by title keyword (kettles/toasters/blenders/irons for small; refrigerators/freezers/washers/water-dispensers for large).
- Pagination via `?page=N`. Site's own paginator only exposes page=2, but higher pages return a "featured" bloc of ~36 products that all appear on page 1 too. Scraper dedupes by URL and stops when a page adds zero new URLs (with a 20-page safety cap).
- Card regex parses container `.col.border-right.border-bottom.has-transition.hov-shadow-out.z-1`, then extracts `<a href="/product/...">`, image url + alt for title, `addToWishList(<id>)` for SKU, and `<span class="fw-700 text-primary">KSh<amount>` for price.
- Registered as `mybigorder-all` / `all-mybigorder` in `TARGETS`, added to `_run_all`, added `all-mybigorder` row to the GH Actions scrape matrix.
- Dry run on Simon's local: parser handled the real HTML cleanly; 4 categories yielded 200 listings before the sample cutoff (phones 37, tablets 16, phone-tablet-accessories 35, laptops 112). Laptops on mybigorder includes chargers/adapters — the downstream matcher will drop the ones that don't parse as brand+model.

## 8g. Shopify batch deprecated from CI (2026-07-28)

All 7 Shopify merchants (digitalcity, zentech, digitalstore, samsung-brandcart, laptopclinic, vividgold, badili — ~2,398 listings combined) stopped scraping ~2026-07-20. Diagnosis and decision:

- **Root cause**: Shopify's platform edge rate-limits `/products.json` per IP. GH Actions Azure IPs return HTTP 429 with body `local_rate_limited`. curl_cffi Chrome impersonation doesn't help — it's IP-reputation-based, not TLS-fingerprint-based.
- **Path Render tried and failed**: routed the batch through Render's Frankfurt IP via a new `/internal/scrape/{target}` endpoint (`app/routes/internal.py`). Render's DC IP is *also* rate-limited (shared pool with other Render tenants who scrape Shopify heavily). Same 429s.
- **Path A tried and failed**: aggressive 429-aware retry (5 attempts, 30-120s waits, respects Retry-After). Rate limit turned out to be sustained not transient — retry just hangs longer without succeeding. Reverted (it also slowed down non-Shopify CffiPoliteClient users on transient errors).
- **Landed on Path C**: removed the `render_shopify` job from `scrape.yml`, deleted the manual `scrape-shopify.yml` workflow. Shopify merchants will decay via the normal FRESHNESS_DAYS window and drop out of the sitemap / product pages naturally.
- **Left in place for future re-enable**: `/internal/scrape/{target}` endpoint (self-diagnostic — captures stdout to the response). Route the scrape through a residential proxy client (ScraperAPI, Bright Data, ~$30/mo entry tier) when ad revenue justifies it. The trigger + endpoint are ready; only the client class needs to change.
- **Impact assessment**: the 7 merchants are dominated by refurbished phones (Badili) and Samsung reseller (BrandCart). Both categories already have solid coverage from Jumia + Kilimall + Phone Place. Loss is uncomfortable (~13% of merchant count) but not fatal to the value prop.

## 8h. WooCommerce merchant outage triage (2026-08-04)

`/admin/scrapes` flagged 6 non-Shopify merchants stale — all `wc-*` matrix legs failing with `ScraperYieldTooLow — yielded ZERO listings but had N on record`. Traced across the last 3 scheduled scrape runs (2026-08-03 → 2026-08-04). Root causes clustered into 3 categories, all fixed in one parallel batch (PRs #1-#5 from six worker agents):

| Merchant | Root cause | Fix | Prior → post |
|---|---|---|---|
| **solarstore-ke** | WordPress frontend throwing "critical error" on every `/product-category/*` (HTTP 500). `/wp-json/wc/store/v1/products` returned clean JSON. | Migrated to shared WC Store API scraper (`scrapers/merchants/solarstore.py` new file). Same escape hatch previously used for finetech / techstore / audiocom / patabay / newmatic. Renamed matrix leg `wc-solarstore-ke` → `solarstore-ke`. | 0 → 46 listings |
| **smartphoneskenya-ke** | GH Actions Azure IPs got HTTP 200 with empty catalog. Same site returned 133 products to residential IPs on plain httpx. | One-line: `client_type: "cffi"`. Chrome TLS impersonation defeats the CI-IP filter. | 0 → 133 (locally verified; CI-only failure) |
| **zuka-ke** | LiteSpeed "Bot Verification" reCAPTCHA challenge page (HTTP 403) on `/product-category/*` for scripted clients. | One-line: `client_type: "cffi"`. Same as smartphoneskenya. | 0 → yielding |
| **megatech-ke** | Not a hard break — intermittent CI failures + shared fetcher silently swallowed exceptions (see below). Also: `/smartphones` had 16 pages but `wc_batch.py` caps at 3, so most SKUs were invisible. | Expanded `leaf_to_urls` with per-brand feeds (samsung, tecno, oppo, iphone…) + added missing `laptops` leaf + dropped merchant-side empty categories. Retained `client_type: "cffi"`. | 235 → 407 unique listings |
| **overtech-ke** | Cloudflare Turnstile challenge was dropped by the merchant. Playwright was overkill (running ~25 min/leg near the 30-min CI budget). | Downgraded `client_type: "playwright"` → `"cffi"`. Retains Chrome TLS fingerprint as a defensive shield-hop; unlocks `max_pages=3` for fuller coverage. Removed from Chromium-install gate in workflow. | 220 → 393 listings, 25 min → ~1 min per leg |
| **techonline-ke** | Strict Cloudflare Managed Challenge ("Just a moment...") on every path except `/robots.txt`. Tried 11 curl_cffi impersonation profiles + Playwright + real installed Chrome + stealth — all 403. | **Deprecated.** Removed from `wc_merchants.py` config and `.github/workflows/scrape.yml` matrix. Catalog is heavily covered by Hotpoint / Fivestar / Dixons / Ramtons anyway. Residential proxy would be needed to revive; not worth the cost. | Removed |

**Systemic fix landed alongside the merchant fixes** (`scrapers/common/woocommerce.py`): the shared fetcher's `except Exception: return` at line 177-178 was silently eating every HTTP failure, so a single 403/429/500 window produced a zero-yield → `ScraperYieldTooLow` with no clue *why*. Diagnosing this outage required re-running each merchant locally with curl to see what the site actually returned. Now the fetcher prints `[wc] <merchant>/<category> page1 GET failed: HTTPError: HTTP 403` and `[wc] ... page1 zero cards (status 200, body head: ...)` so the next outage surfaces the actual reason in the CI log. Same pattern as `scrapers/common/shopify.py`'s page-1 diagnostic (shipped in commit `0d898e6` during the 2026-07-28 Shopify triage).

**Coordinator commit also unblocked CI** by registering `now()` as a Jinja global in `app/templating.py` (`product.html` references `{{ now().year }}` in the title block — without the registration, every rendered product-page test raises `UndefinedError`). Previously staged as WIP that never got committed.

**Not fixed by this batch** — pre-existing "1 NEVER SCRAPED" merchant flagged in `/admin/scrapes`. Different failure mode from the 6 above (never got a first scrape at all, not a regression from a working state). Deferred.

**Outcome**: 6-of-6 broken merchants resolved (5 fixed, 1 deprecated). WooCommerce fetcher no longer silently eats errors. Next stale-merchant outage should be diagnosable from a CI log line rather than a re-run + local-curl loop.

## 8i. Second WC outage triage (2026-08-11)

One week after §8h, `/admin/scrapes` flagged 4 more merchants stale (+ 1 infra blip):

| Merchant | Symptom in CI | Local (KE IP) reality | Fix | PR |
|---|---|---|---|---|
| wc-tclke-ke (87 prior) | `RetryError[HTTPStatusError]` on every leg | `curl_cffi` returns 200 with 198KB DOM per page, selectors intact | `client_type: "cffi"` | #16 |
| wc-zuka-ke (42 prior) | `RetryError[Timeout]` — packets dropped at network layer | LiteSpeed firewall drops GHA IPs before any HTTP handshake; even Playwright/Render pool shares the same burned IPs | **Deprecated**. Categories covered by Hotpoint / Fivestar / Housewife's Paradise / Kilimall / Jumia. | #14 |
| wc-housewife-ke | 200 + JS-refresh challenge shell served to GHA IPs by WP Rocket / bot mitigation | Both plain httpx AND curl_cffi return the real 750KB WooCommerce HTML | `client_type: "cffi"` (same tactic as tclke) | #15 |
| patabay-ke (435 prior) | Zero-yield in ~7s with NO diagnostic prints; Cloudflare IP-reputation blocking | curl_cffi from KE IP yields 788 listings across 13-page catalog | Bigger fix — see below | #17 |
| `all-laptops` | `psycopg.OperationalError: Network is unreachable` on Neon IPv6 addresses | N/A (infrastructure) | No action — transient | — |

**Pattern this week:** every non-deprecated failure was CI IP-reputation-based, and every one solved with `cffi` (Chrome TLS impersonation) or `playwright-stealth`. Kenyan merchants are progressively rolling out bot-posture rules; regex/selectors are fine.

**patabay-ke fix (PR #17) was more than one line:**
- Added a `client_type` parameter to the shared `fetch_wc_store_catalog` (`scrapers/common/wc_store_api.py`) — mirrors the pattern in `scrapers/common/woocommerce.py`.
- Added page-1 diagnostic prints to every silent-return branch (GET exception, HTTP 4xx/5xx, JSON parse fail, empty products). Previously the WC Store API scraper ate all failure signatures silently — same class of blindness §8h/§8g addressed for woocommerce.py + shopify.py.
- New `_extract_json_payload` helper strips Chromium's `<pre>JSON</pre>` wrapper so `json.loads` works on both raw-httpx bodies and Playwright-navigated ones.
- Switched patabay to `client_type="playwright-stealth"`, bumped `max_pages` 60 → 15, added Chromium install gate.

**Worktree gotcha for future /batch runs:** worker prompts that include `cd ~/work/pricekenya` move OUT of the assigned isolated worktree back into the main working copy — one worker's initial edit landed in the main worktree on the wrong branch and had to be re-applied. Fix in future batches: use `cd $CLAUDE_WORKTREE_PATH` or omit `cd` entirely.

**Cumulative merchant loss YTD:** 7 Shopify (§8g) + 1 techonline (§8h) + 1 zuka (§8i). All three loss causes fundamentally need paid infrastructure (residential proxy pool) to revive. Every other outage was fixed with a config flip.

## 8j. Third stale-merchant triage (2026-08-21)

`scripts.scrape_health` flagged **11 stale merchants**, but only **2 were new breakage** — the other 9 are the already-deprecated §8g/§8h/§8i merchants whose rows sit in the DB decaying, which is the designed behaviour and not a signal. Worth recording because the raw stale count now overstates the problem by 5x; read it against the deprecation list, not on its own.

| Merchant | Stale for | Diagnosis | Action |
|---|---|---|---|
| **housewife-ke** | 18h (leg red) | Bot posture escalated **past cffi**. Every category logged `page1 zero cards (status 200, body head: ...setTimeout(...window.location.reload...))` in run `32485421591` → `ScraperYieldTooLow`. Second escalation for this merchant — §8i moved it httpx → cffi only 10 days earlier. | `client_type: "playwright-stealth"` + Chromium install gate. |
| **finetech-ke** | 400h | **Not a bot block — the merchant is gone.** `finetech.co.ke` is NXDOMAIN at both 8.8.8.8 and 1.1.1.1; the domain lapsed. (`finetech.ke` resolves but is an unrelated parked Namecheap host; Google still serves indexed snapshots of the old site, which is misleading.) CI logged `[wc-store] finetech-ke page1 GET failed: RetryError[...DNSError]` on every run since ~2026-08-05. | **Deprecated.** Removed from matrix + `wc_merchants.py`, `scrapers/merchants/finetech.py` deleted, `run_finetech`/TARGETS entry removed. 12 listings; catalog fully covered by Jumia / Kilimall / Phone Place / Avechi. |

**The finetech lesson — a 400-hour outage with green CI.** `MIN_PRIOR_LISTINGS_FOR_CHECK` was 20. Finetech had 12 listings on record, so `_assert_yield_healthy` returned early, the leg exited 0, and no Telegram alert ever fired. The dead domain was only found by reading `scrape_health` output by hand. **Lowered the floor 20 → 5.** This is safe: the false positives that floor exists to suppress come from per-category legs (`all-phones`, `all-tvs`…) whose `prior_count` is the merchant's *whole-catalog* total — Jumia 2301, Kilimall 1679, Hotpoint 217, all far above either threshold. The only merchants whose behaviour changes are the 5-19-listing band, and every one of those is a single-leg full-catalog scrape where zero genuinely is a failure. `tests/test_yield_check.py` now derives its bound from the constant instead of hardcoding it, which is why the old value went unnoticed.

**Closed a latent race in the Playwright client while we were in here.** `PlaywrightPoliteClient.get` sleeps 4s, then waits for `networkidle` (6s cap), then reads `page.content()`. The WP-Rocket-style shell reloads itself at **5000ms** and issues no network requests, so `networkidle` resolves almost immediately — meaning the read can land at ~t=4.5s and capture the *shell* rather than the reloaded real page.

Note this is a latent race, not an observed failure: megatech runs green on playwright-stealth, which suggests the mitigation usually doesn't serve the shell to a stealth Chromium in the first place (it passes the fingerprint check and gets the real page on the initial navigation). But the window is real and would bite silently — as a zero-yield with a Chromium bill attached — the first time a merchant does serve it. Added `_is_js_refresh_shell()` (`scrapers/common/base.py`): when the returned DOM matches the stub signature (contains `window.location.reload`, under 20KB — a real WC category page is 100s of KB), wait out the reload and re-read; if the shell survives that, raise, so tenacity's 3 attempts run on the same browser context and a persistent block dies loudly instead of silently zero-yielding. Cost is only paid when the shell is actually served, so megatech / patabay / hisense see no regression.

**megatech-ke corroborates the housewife diagnosis — read it before doubting the Playwright cost.** megatech hit this same JS-refresh shell on 2026-08-11 and moved cffi → playwright-stealth in PR #19. It has been green on playwright-stealth every cycle since (run `32485421591`: Chromium install step ran, scrape step clean, zero diagnostics, 317 listings fresh at 6.9h). So the escalation is real, it does not spontaneously resolve, and Playwright is the fix that holds. housewife-ke is the second merchant on the same platform stack to make the same jump 10 days later.

**Methodology warning for whoever triages next.** During this pass the megatech change was briefly, wrongly reverted on the theory that the escalation had been transient and cffi still worked. The error: `git diff main...HEAD` was run against a **stale local `main`** that predated PR #19's squash-merge, which made an already-merged change look like unmerged local work, and the clean CI logs that "proved cffi was fine" were in fact playwright-stealth runs. `git fetch` before reading any branch as unmerged, and confirm which client a green run actually used — the job's step list shows whether `Install chromium` ran.

**Known trade-off on housewife:** `wc_batch.py` sets `max_pages = 1` for Playwright clients (vs 3 for cffi), so page-2/3 coverage is lost. 14 category URLs × ~20 cards/page still covers most of the 167 listings on record, and partial coverage beats the zero it yields today. Revisit if the count drops sharply.

**Not acted on:** `sollatek-ke` shows `never scraped` in `scrape_health`. That's not an outage — it was deliberately never wired up (see the comment in `shopify_merchants.py`: `shop.sollatek.com` sells voltage guards/AVS units with no category overlap). It's a stray `Merchant` row creating a permanent false positive on the health report; delete the row or teach the report to skip merchants with no configured target.

## 8k. Fourth stale-merchant triage (2026-08-29)

No DB access this pass (no `DATABASE_URL` in this environment, so `scripts.scrape_health` couldn't run) — signal came entirely from the GH Actions `scrape.yml` matrix, which is sufficient now that `MIN_PRIOR_LISTINGS_FOR_CHECK` sits at 5 (§8j): a zero-yield leg fails red instead of exiting 0 silently.

Covered the last 4 scheduled runs (2026-08-27 09:46 → 2026-08-28 22:18). Three legs failed somewhere in that window; only one was persistent.

| Merchant | Run(s) | Symptom | Verdict |
|---|---|---|---|
| **overtech-ke** | 33166873237 (08-28 11:22), 33216269580 (08-28 22:18) — 2/2 most recent, was green through 08-27 22:15 | Every leaf (`audio`, `cameras`, `console-accessories`, `laptops`, `peripherals-accessories`, `phone-tablet-accessories`) logged `[wc] overtech-ke/<leaf> page1 GET failed: RetryError: RetryError[<Future ... raised Timeout>]` — no HTTP response reached the client at all, on `client_type: "cffi"`, which had been holding since the 2026-08-04 Turnstile-drop fix (§8h). `overtech.co.ke` still resolves in DNS (not dead). | **Deprecated.** Same signature as zuka-ke/nairobitvshop-ke (§8i/8j) — GHA IPs dropped at the network layer, not a TLS or challenge problem `client_type` can fix. Residential-proxy Playwright is the only path back; not worth it for a 239-listing catalog (audio/cameras/laptops/accessories) already covered by Jumia/Kilimall/Hotpoint/Phone Place. Removed from `scrape.yml` matrix and `wc_merchants.py`. |
| wc-smartphoneskenya-ke | 33121723127 (08-27 22:15) only | `failure` conclusion, but green on the run immediately before and both runs after. | **Noise.** One-off CI blip, not re-verified as a pattern — no action, per the megatech-ke lesson in §8j about not chasing a single red run. |
| wc-eamobitech-ke | 33060088510 (08-27 09:46) only | Same — `failure` once, green on every other run in the window. | **Noise.** Same reasoning. |

**Why two of the four runs showed as `cancelled` instead of `failure` at the top level.** `phonesstore-ke` shows `conclusion: cancelled` in both runs where overtech-ke failed. The matrix strategy's default `fail-fast: true` cancels any leg still queued/running when another leg in the same matrix fails — `phonesstore-ke` was mid-queue when `wc-overtech-ke` raised, so it got cancelled, which drags the whole run's top-level conclusion to `cancelled` even though the real failure is `wc-overtech-ke`'s red leg underneath. Read `list_workflow_jobs` per-leg, not the run-level conclusion, when triaging — a `cancelled` run can be hiding a genuine break.

**Cross-check against the deprecation list.** All other legs in the 4-run window were green throughout, and none of the already-deprecated merchants (7 Shopify, techonline-ke, zuka-ke, finetech-ke, nairobitvshop-ke, sollatek-ke's stray row) triggered anything — consistent with §8j's point that they're not wired into the matrix any more so they can't produce CI signal at all now.

## 8l. Fifth stale-merchant triage (2026-09-03)

Same constraint as §8k — no `DATABASE_URL` in this environment, signal came entirely from the `scrape.yml` matrix on GH Actions.

Covered the last 4 scheduled runs (2026-09-01 16:38 → 2026-09-03 04:31, runs `33533028249` → `33715378198`). One leg was persistent; the rest were single-run blips.

| Merchant | Run(s) | Symptom | Verdict |
|---|---|---|---|
| **wc-eamobitech-ke** | 33533028249, 33591161024, 33655640018, 33715378198 — 4/4 in the window | Every leaf (`audio`, `cameras`, `laptops`, `peripherals-accessories`, `phones`, `tablets`, `tvs`) logged `[wc] eamobitech-ke/<leaf> page1 GET failed: RetryError: RetryError[<Future ... raised HTTPStatusError>]` on plain httpx (`client_type` was unset — default `"polite"`), tripping `ScraperYieldTooLow: eamobitech-ke: yielded ZERO listings but had 52 on record`. `eamobitech.com` resolves fine to Cloudflare IPs (`104.26.4.215`, `2606:4700:...`) — not a dead domain, not a network-layer drop (an actual HTTP response came back, just one httpx's default fingerprint can't get past). Same discrimination pattern as tclke-ke/megatech-ke/smartphoneskenya-ke (§8h/§8i). This is the same merchant §8k logged as a one-off blip on 2026-08-27 (green everywhere else in that window) — it has since gone persistent. | **Fixed.** One-line: `client_type: "cffi"` in `wc_merchants.py`. No workflow change needed (cffi doesn't touch the Chromium install gate). |
| wc-megatech-ke | 33591161024 (09-02 04:31) only, `cancelled` | `wc-eamobitech-ke` failed earlier in the same matrix run and `fail-fast: true` cancelled `wc-megatech-ke` mid-queue (same mechanism §8k documented for `phonesstore-ke`) — not a real megatech break. Green on the runs immediately before and after. | **Noise** (cascade artifact of the eamobitech failure, not megatech's own). No action. |
| all-mybigorder, audiocom-ke | 33655640018 (09-02 16:33) only | Both `failure`, but green on the runs immediately before and after. | **Noise.** One-off CI blip, not re-verified as a pattern — per the megatech-ke lesson in §8j. |
| wc-devicestech-ke | 33533028249 (09-01 16:38) only | `failure`, green on the runs immediately before and after. | **Noise.** Same reasoning. |

**Cross-check against the deprecation list.** No already-deprecated merchant (7 Shopify, techonline-ke, zuka-ke, finetech-ke, overtech-ke, nairobitvshop-ke, sollatek-ke's stray row) produced any signal in this window — consistent with them no longer being wired into the matrix.

## 8m. Sixth stale-merchant triage (2026-09-05)

Same constraint as §8k/§8l — no `DATABASE_URL` here, signal came entirely from the `scrape.yml` matrix. Covered the last 8 scheduled runs (2026-09-01 16:38 → 2026-09-05 04:26, runs `33533028249` → `33944551667`); every one of the 8 was red at the top level, so this pass leaned on per-leg job status (`list_workflow_jobs`), not run conclusion, to separate persistent breaks from cascade/noise.

**PR #35 (eamobitech-ke → cffi) was already open from the prior triage (§8l, 2026-09-03) and had not been merged** — that is why `wc-eamobitech-ke` is still red in every run through 2026-09-05 despite already having a fix sitting on a branch. Nothing new to do here except flag it: the fix in #35 matches this run's log lines exactly, it isn't stale (still branched off the current `main` tip), and it just needs review/merge. Not re-diagnosed or re-fixed in this pass — opening a duplicate PR would only create a merge conflict with #35 once it lands.

| Merchant | Run(s) | Symptom | Verdict |
|---|---|---|---|
| **wc-solarshop-ke** | 33778433274, 33837128114, 33894560006, 33944551667 — 4/4 most recent, green on the two runs before that (33715378198, 33655640018) | Every leaf (`inverters`, `solar-batteries`) logged `[wc] solarshop-ke/<leaf> page1 GET failed: RetryError: RetryError[<Future ... raised HTTPStatusError>]` (one leg also raised `ConnectError`) on plain httpx (`client_type` was unset), tripping `ScraperYieldTooLow: solarshop-ke: yielded ZERO listings but had 29 on record`. Same TLS-fingerprint discrimination pattern as tclke-ke/eamobitech-ke/smartphoneskenya-ke. | **Fixed** (PR #36). One-line: `client_type: "cffi"`. No workflow change needed. |
| **wc-tclke-ke** | Red across the same window checked (confirmed persistent in the newest run, `33944551667`, job `101248249291`) | Already on `client_type: "cffi"` since §8h/§8i — that fix is not what's failing now. Every leaf logs `page1 zero cards (status 200, body head): '<!DOCTYPE html> <html lang="en"> <head> <script> (function () { var proto = XMLHttpRequest.prototype; ... var TOKEN_KEY = \'base44_access_token\'; ...'`. This is not the WP-Rocket/Cloudflare `window.location.reload` JS-refresh shell §8j and housewife-ke/megatech-ke escalated past (this body doesn't match that signature at all) — it reads as a genuine front-end rebuild on a token-gated JS app shell (a client-side auth wrapper intercepting `XMLHttpRequest`, unrelated to WooCommerce's server-rendered category markup). `ScraperYieldTooLow`'s own message says it plainly: "Almost certainly a site rebuild." Tried to verify further — `curl` and `WebFetch` against `tclke.co.ke` both come back `EGRESS_BLOCKED` from this environment's network policy, so there is no way to confirm from here whether products are still reachable behind the shell (e.g. via a JSON endpoint the SPA calls) or whether this is a dead end requiring a full scraper rewrite. | **Not fixed — inconclusive.** Flipping `client_type` again would be a guess: even `playwright-stealth` would only get further if the underlying markup is still WooCommerce-shaped once JS runs, and nothing in the log confirms that. Needs a manual check of `tclke.co.ke` from a real browser/residential IP (or DB access to see how long 88 listings have been decaying) before deciding between a scraper rewrite and deprecation. Not deprecated either — DNS resolves and the failure isn't a network-layer block, so the §8j/§8k/§8l deprecation criteria don't cleanly apply. Left as-is pending that check. |
| wc-hisense-kenya-ke | 33778433274, 33837128114 (the two oldest in this window) only | Cloudflare Turnstile challenge, same as always — failed twice then green on both of the two newest runs. | **Noise.** Recovered on its own; not re-verified as a pattern, per the megatech-ke lesson in §8j. |
| all-mybigorder | 33944551667 (newest) and 33655640018 (6 runs back) only, non-consecutive | `failure` both times but green on every run in between. | **Noise.** Two isolated blips, not a persistent break. |
| phonesstore-ke | 33944551667, 33894560006 — `cancelled`, not `failure` | Same fail-fast cascade §8k documented: `wc-tclke-ke`/`wc-solarshop-ke`/`wc-eamobitech-ke` failing earlier in the matrix cancelled `phonesstore-ke` mid-queue. Not a real phonesstore break. | **Noise** (cascade artifact). No action. |

**Cross-check against the deprecation list.** No already-deprecated merchant (7 Shopify, techonline-ke, zuka-ke, finetech-ke, overtech-ke, nairobitvshop-ke, sollatek-ke's stray row) produced any signal in this window.

**Methodology note.** Local `main` was 2 commits behind `origin/main` at the start of this pass (the exact trap §8j warned about) — caught by `git branch -vv` showing `[origin/main: behind 2]` before branching, and fixed with `git rebase origin/main` before any commit. Branching off a stale local `main` here would have silently reintroduced whatever main had already fixed since.

## 8n. Seventh stale-merchant triage (2026-09-09)

Same constraint as §8k-8m — no `DATABASE_URL` in this environment, signal came entirely from the `scrape.yml` matrix (`MIN_PRIOR_LISTINGS_FOR_CHECK` at 5 since §8j, so a zero-yield leg fails red instead of exiting 0 silently). Also no `curl`/`WebFetch` egress from this environment — confirmed again this pass (`CONNECT tunnel failed, response 403` on every probed domain) — so diagnosis leaned entirely on CI log content plus DNS (`socket.gethostbyname_ex`, which does work).

Covered the last 4 **completed** scheduled runs (2026-09-07 04:39 → 2026-09-08 16:36, runs `34083907559` → `34252143451`; a 5th run, `34311869380`, was still in progress at triage time and not counted). Between §8m (2026-09-05) and this pass, main had already picked up PR #38 (eamobitech-ke → cffi + tclke-ke deprecated), #36 (solarshop-ke → cffi), #41 (smartdevices-ke → cffi) and #40 (a duplicate-key cleanup from #36/#38 colliding) — so this pass started from a materially different `main` than §8m saw, with three of §8m's open items already landed.

| Merchant | Run(s) | Symptom | Verdict |
|---|---|---|---|
| **wc-smartdevices-ke** | 34083907559, 34148815845, 34187430656, 34252143451 — 4/4 | Already flipped to `client_type: "cffi"` by PR #41 (landed 2026-09-07, before the first of these 4 runs) for a prior TLS-fingerprint block. The fix didn't hold: every leaf failed in every run, `[wc] smartdevices-ke/<leaf> page1 GET failed: RetryError: RetryError[<Future ... state=finished raised HTTPError>]` — curl_cffi's own `HTTPError` (a real HTTP error status under Chrome TLS impersonation), not httpx's `HTTPStatusError` and not a `ConnectTimeout`/`Timeout`. Rules out both the plain-TLS-fingerprint pattern (cffi already applied) and the network-layer-drop pattern (zuka-ke/overtech-ke — those show as `Timeout` with no HTTP response at all). Matches the past-cffi escalation megatech-ke/housewife-ke already went through. | **Fixed** (PR #42). `client_type: "playwright-stealth"` + added to the Chromium install gate. |
| **wc-eamobitech-ke** | 34148815845, 34187430656, 34252143451 — 3/4, green on 34083907559 (the oldest, only hours after PR #38's cffi fix landed) | Identical signature and identical escalation to smartdevices-ke, one run later: cffi (from PR #38, §8m/OPERATIONS history) held for exactly one scheduled run then started throwing `RetryError[HTTPError]` on every leg. | **Fixed** (PR #43). Same escalation, same fix: `client_type: "playwright-stealth"` + Chromium gate. Filed as a separate PR from smartdevices-ke to keep each diff to one merchant, per the task's own instruction. |
| wc-quest-ke | 34252143451 (newest) only | `[wc] quest-ke/<leaf> page1 zero cards (status 200, body head): '...setTimeout(function(){ window.location.reload(); }, 5000)...'` on every leaf — the exact WP-Rocket-style JS-refresh shell signature from §8j/8m (housewife-ke, megatech-ke). But green on all 3 runs before it (confirmed via full job list, not just the failing subset). | **Noise, provisionally** — one run only, not yet re-verified per the megatech-ke lesson. Flagging because the signature is a clean bot-mitigation match rather than generic flakiness (unlike a typical single-run blip); if it recurs next pass, the fix is `playwright-stealth` + Chromium gate, no further diagnosis needed. |
| solarstore-ke | 34252143451 (newest) only | `[wc-store] solarstore-ke page1 GET failed: RetryError: RetryError[<Future ... raised HTTPError>]` — same signature class as smartdevices-ke/eamobitech-ke, but on the WC Store API scraper (`fetch_wc_store_catalog`), not the woocommerce.py category-page path. Green on all 3 runs before it. | **Noise, provisionally** — same reasoning as quest-ke: one run, not yet a confirmed pattern. Worth a second look next pass given it's the same failure class currently escalating on two other merchants. |
| wc-hisense-kenya-ke | 34187430656 only | Cloudflare Turnstile challenge, same as always. Failed once, green on both the run before and the two runs after. | **Noise.** Recovered on its own. |

**Cross-check against the deprecation list.** No already-deprecated merchant (7 Shopify, techonline-ke, zuka-ke, finetech-ke, overtech-ke, nairobitvshop-ke, tclke-ke, sollatek-ke's stray row) produced any signal in this window.

**Pattern worth flagging.** Three merchants now in one week (housewife-ke and megatech-ke earlier, smartdevices-ke and eamobitech-ke this pass, quest-ke/solarstore-ke possibly next) have hit the same cffi → playwright-stealth escalation. It reads less like isolated per-merchant bot-posture changes and more like a Cloudflare-side policy update that's rolling out account-by-account or tier-by-tier across the Kenyan WooCommerce hosting base — cffi's Chrome-TLS-impersonation trick may be heading toward "was a temporary loophole" rather than "the standing fix." Not actionable yet (no way to confirm the theory without DB history of *when* each merchant's Cloudflare plan changed), but if a third and fourth merchant escalate past cffi next week, this is worth raising as a trend rather than triaging each one as a fresh surprise.

## 8o. Eighth stale-merchant triage (2026-09-11)

Same constraint as §8k-8n — no `DATABASE_URL` and no `curl`/`WebFetch` egress in this environment (`CONNECT tunnel failed, response 403` on every probed domain, confirmed again this pass); diagnosis leaned on CI log content plus DNS (`socket.gethostbyname_ex`, which does work). One difference from prior passes: the `health` job's own log (job step "Fail if any active merchant is stale") prints the full per-merchant coverage table with `DATABASE_URL` available *inside CI*, so this pass could read exact staleness ages (227h, 108h, 60h below) straight from the job log without DB access of its own.

Covered the last 4 scheduled runs (2026-09-09 04:40 → 2026-09-10 16:23, runs `34311869380` → `34501761493`). All 4 were red at the top level; per-leg job status (not run conclusion) separated persistent breaks from cascade/noise, per the §8k methodology note.

**3 BROKEN per the health job's own count** (active & stale > 30h): eamobitech-ke (227.4h), smartdevices-ke (108.1h), solarstore-ke (60.0h). All three showed up as persistent 4/4 failures in the matrix too.

| Merchant | Run(s) | Symptom | Verdict |
|---|---|---|---|
| **solarstore-ke** | 34311869380, 34377874909, 34438111965, 34501761493 — 4/4, green through 33778433274 (§8m) | `[wc-store] solarstore-ke page1 GET failed: RetryError: RetryError[<Future ... raised HTTPError>]` on curl_cffi (the WC Store API scraper's default `client_type`) — curl_cffi's own HTTP error status, not a `Timeout`/`ConnectTimeout`. Identical signature class to the one that already forced smartdevices-ke and eamobitech-ke from cffi to playwright-stealth (§8n), and the same IP-reputation pattern patabay-ke/hisense-kenya-ke already hit on this same WC Store API path. Flagged "noise, provisionally" in §8n on a single run; now confirmed persistent across all 4 runs checked this pass. | **Fixed.** `client_type="playwright-stealth"` passed to `fetch_wc_store_catalog()` in `scrapers/merchants/solarstore.py` + added `solarstore-ke` to the workflow's Chromium install gate. No `max_pages` adjustment needed — the catalog is 46 listings, well under one `per_page=100` page. |
| **wc-smartdevices-ke** | 34377874909, 34438111965, 34501761493 — 3/3 since PR #42 (playwright-stealth) landed; 34311869380 (the run just before) still failed on the old cffi client with `RetryError[HTTPError]`, matching §8n's diagnosis exactly | The PR #42 escalation did *not* hold. Every category in every run since logs `page1 zero cards (status 522 or 523, body head): '<html><head></head><body></body></html>'` — Cloudflare's own "origin connection timed out" (522) / "origin unreachable" (523) error pages, served with an empty body. This is not a JS-refresh shell (no `window.location.reload`, no script at all) and not a Cloudflare challenge (no `cf-mitigated`, no "Just a moment..." title) — Playwright is getting a real navigation response, it's just Cloudflare itself reporting it cannot reach smartdeviceskenya.co.ke's origin server. DNS resolves fine (`172.67.211.59`, `104.21.45.78`, both Cloudflare anycast) so the domain is not gone, and this doesn't match the network-layer-drop pattern either (that shows as `RetryError[Timeout]` with no HTTP response at all, not a CF-issued 522/523). | **Not fixed — inconclusive, no PR opened.** `playwright-stealth` is the top of this codebase's escalation ladder (grep for `client_type ==` in `scrapers/common/*.py` — nothing past it exists), so there is no further client-side change to try, and 522/523 reads as a merchant-side origin outage that no client configuration can route around. Doesn't meet either textbook deprecation criterion (dead domain / network-layer packet drop), so not deprecated per this task's own bar against acting on a fix that "looks fiddly." Left as-is; re-check next pass — if the 522/523s continue for another week with no green run in between, that's worth escalating from "transient origin outage" to "merchant's hosting has failed" as a deprecation case. |
| **wc-eamobitech-ke** | 34377874909, 34438111965, 34501761493 — 3/3 since PR #43 (playwright-stealth) landed; the run just before it (34311869380) was green (the fix had just landed and held for exactly one run) | Also did not hold past one scheduled run. Every leg logs `RetryError: RetryError[<Future ... raised RuntimeError>]` — tenacity's `RetryError` repr only names the exception *class*, not its message, and `str(exc)` in the diagnostic print (`scrapers/common/woocommerce.py:200-202`) doesn't dig into `exc.last_attempt.exception()`, so the actual text is lost. The only two `RuntimeError`s `PlaywrightPoliteClient.get` ever raises (`scrapers/common/base.py:153`, `:166`) are "JS-refresh challenge unresolved" and "Cloudflare challenge unresolved ... title='Just a moment...'" — both mean the stealth-patched headless Chromium successfully navigated and got a response, but Cloudflare is still serving it a challenge page rather than the real WooCommerce category page. Same conclusion as smartdevices-ke: not a dead domain (`eamobitech.com` resolves to 3 Cloudflare IPs), not a raw network-layer drop (an HTTP response comes back every time). | **Not fixed — inconclusive, no PR opened.** Same reasoning as smartdevices-ke: `playwright-stealth` is already the strongest client this codebase has, and a challenge that survives stealth Chromium reads as an IP-reputation block on the GHA runner pool rather than anything client-side-fixable — the same root cause class as the Shopify batch deprecated in §8g, but that precedent required an unambiguous, sustained (weeks, not days) block before deprecating, and this is one pass past the fix landing. Left as-is pending another triage cycle; if it's still failing next pass with no green run in between, this becomes a genuine deprecation candidate (IP-reputation block, residential-proxy-only) rather than a "give the fix time to prove itself" case. |
| wc-megatech-ke, wc-smartphoneskenya-ke | 34377874909 only | Both `failure`, green on the run immediately before and both runs after. | **Noise.** One-off CI blips in the same run, not re-verified as a pattern — per the megatech-ke lesson in §8j. |
| phonesstore-ke, wc-housewife-ke | 34377874909, 34438111965 (phonesstore-ke); 34438111965 (wc-housewife-ke) — `cancelled`, not `failure` | Same fail-fast cascade §8k/§8m documented: `wc-smartdevices-ke`/`solarstore-ke`/`wc-eamobitech-ke` failing earlier in the matrix cancelled these mid-queue. Not real breaks. | **Noise** (cascade artifact). No action. |

**quest-ke and hisense-kenya-ke did not recur** in this window (no signal in any of the 4 runs checked) — both stayed as one-off blips per §8n's "provisional noise" call, not confirmed patterns.

**Cross-check against the deprecation list.** No already-deprecated merchant (7 Shopify, techonline-ke, zuka-ke, finetech-ke, overtech-ke, nairobitvshop-ke, tclke-ke, sollatek-ke's stray row) produced any signal in this window.

**The §8n "pattern worth flagging" is confirmed, not resolved.** §8n predicted that a third and fourth merchant escalating past cffi within a week would turn "isolated bot-posture changes" into "a rolling Cloudflare policy change" worth treating as a trend. That happened (solarstore-ke this pass), but this pass adds a sharper, more worrying data point on top: two of the merchants that *already made* the cffi → playwright-stealth jump (smartdevices-ke, eamobitech-ke) stopped holding on playwright-stealth within one scheduled cycle of landing. If that repeats on solarstore-ke's fix next pass, the conclusion isn't "escalate again" — there's nothing left in this codebase to escalate to — it's "GitHub Actions' IP pool is being blocked outright by these merchants' Cloudflare tier, independent of client fingerprint," which only a residential proxy (the same conclusion §8g reached for Shopify) can fix.

