# PriceKenya — Project Context

The canonical document for *why* this project exists, *what* it is, and *how* decisions were made. Update this when you learn something material — it's how future-you (and any agent) gets up to speed without re-doing research.

Last updated: 2026-07-06

---

## 1. The pitch in one paragraph

A price-comparison site for the Kenyan market, modelled on prisjakt.no (Norway) / PriceSpy. Users search a product, see prices from multiple Kenyan merchants side-by-side, view price history, and set drop alerts. Monetised first via affiliate (Jumia), later via display ads and merchant CPC. Mobile-first, since ~70% of Kenyan e-commerce traffic is mobile.

## 2. Market context (as of 2026-06)

- **Kenya is the 3rd largest e-commerce market in Africa.** Market reached KSh 299.45B in 2024. ~40M e-commerce users projected by end of 2026.
- **Mobile dominates**: 70%+ of e-commerce transactions on mobile. Smartphone penetration ~83.5%.
- **M-Pesa is the payment rail**: 70%+ of online transactions go through it. ~50M transactions/day across Kenya. Daraja API enables direct integration.
- **Competitive landscape**:
  - **Jumia Kenya** — biggest catalog, has affiliate API.
  - **Kilimall** — strong on cheaper Chinese brands; prices often 10–20% lower than Jumia for budget electronics.
  - **Sky.Garden** — fading.
  - **Copia** — shut down 2024.
  - Specialists: Phone Place Kenya, Avechi, Hotpoint, HiFi Corp, Safaricom Shop.
  - Informal: WhatsApp business catalogs, Instagram shops, Facebook Marketplace. Important but messy — deferred to v2.

## 3. How prisjakt.no works (reference model)

- **Data**: merchants submit structured product feeds (Avecdo-style). Prisjakt does *not* primarily scrape.
- **Revenue**: cost-per-click charged to merchants, plus display ads and ad-solution packages. Not affiliate-on-sale.
- **Features beyond price compare**: price history, drop alerts, expert/user reviews, wishlists, deep category taxonomy, an in-app AI advisor (thin layer over the product graph).
- **Operates as**: Prisjakt (Norway/Sweden), PriceSpy (UK/IE/NZ), Hintaopas (FI), Pagomeno (IT), leDénicheur (FR). Estimated revenue ~$10M.

## 4. How we differ for Kenya

We can't copy prisjakt's data model. Kenyan merchants don't publish clean feeds. Implications:

1. **Scrape, don't ingest.** Until merchants are convinced to push feeds, we pull HTML on a schedule. Jumia has an affiliate API — use it where possible.
2. **Product matching is the hard problem.** A Jumia listing "Tecno Spark 30C 5G 8GB+256GB" must merge with Kilimall's "Tecno Spark 30 C (8+256)" to be useful. Without good matching, we have two half-broken pages instead of one good one. This is where AI eventually earns its budget (embeddings + LLM disambiguation), not in the search box.
3. **Total cost > sticker price.** Delivery fee to county + M-Pesa charge + COD fee can flip "cheapest" between merchants. v1: add a county/payment selector that re-ranks offers by *landed* cost.
4. **Trust signals.** Counterfeit phones are a real Kenyan concern. Showing price-vs-history flags suspicious lowballs ("60% below 30-day average → likely counterfeit").

## 5. Is AI actually necessary?

**Short answer**: not for the search box, yes for matching.

| Use | Verdict |
|---|---|
| Conversational search ("Tecno phone under 20k with good battery") | Cherry on top, not the headline UX. Kenyan shoppers know what they want and want a fast price list. Build later. |
| Product matching across merchants | Worth every cent. Deterministic rules cover 70%; LLM disambiguates the rest. |
| Review summarisation | Useful, easy, free traffic on long-tail "is X any good in Kenya" queries. v1. |
| Counterfeit-spotting from listing language | High-value, easy to bolt on once we have history. v1. |
| Image-based search | Defer to v3+. |

## 6. Stack decisions

| Layer | Choice | Why |
|---|---|---|
| Backend | **FastAPI** | Async-friendly for scraping; clean DI; quick to ship. |
| Templates | **Jinja2 + HTMX + Alpine + Tailwind CDN** | Server-rendered HTML is the SEO gold standard (every product page must rank for `<model> price in Kenya`). HTMX gives interactivity without a build step. No JS bundle to babysit. |
| ORM | **SQLModel** | Pydantic + SQLAlchemy in one. Smooth with FastAPI. |
| DB | **SQLite (dev) → Postgres on Neon (prod)** | Free tier covers v0; we keep schema portable. |
| Scraping | **httpx + selectolax** for static; **Playwright** as an opt-in extra | Selectolax is *fast* — important when scraping a few thousand pages/day on a free-tier VM. Playwright only when needed (JS-only renders, anti-bot checks). |
| Matching | Deterministic regex + slug canonical key; LLM hook left open | Cheap, debuggable, covers majority of titles. |
| Scheduling (dev) | APScheduler | Works in-process. |
| Scheduling (prod) | **GitHub Actions cron** | Free 2000 min/mo, no infra. |
| Hosting | **Render (web) + Neon (DB) + GitHub Actions (cron)** | All truly free. Render's cold start is acceptable for v0. Oracle Cloud Always Free is the upgrade path if we outgrow Render. |
| Frontend framework | Considered **Next.js**, rejected for v0 | Two services / two languages slows solo iteration; SSR is not unique to Next; HTMX covers our interactivity. Reconsider if we want a polished mobile-app shell or want React contributors. |

## 7. v0 scope (what's in the repo today)

- Folder structure + dependencies pinned in `pyproject.toml`
- SQLModel schema: Merchant, Product, Listing, PriceHistory, Alert
- Deterministic title parser + match-or-create
- Jumia Kenya phones scraper (top 3 pages)
- Ingest pipeline: scrape → match → upsert listing → record price history
- FastAPI routes: home, search (HTMX live-results), product detail, click-out redirect, alert signup
- Server-rendered Jinja templates with Tailwind via CDN
- Seed loader (5 merchants, 12 sample listings, 30 days fake history) so the site runs end-to-end without scraping
- Alert dispatcher (stdout v0)
- APScheduler runner for local dev
- README with run + free-tier deploy instructions

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

## 9. Roadmap

### v0.5 — make it production-credible
- Real scrapers for Kilimall, Phone Place, Avechi, Safaricom Shop
- Click logging (`out/{listing_id}` → write a Click row before redirect) for revenue attribution
- robots.txt + sitemap.xml generated from DB
- JSON-LD `AggregateOffer` (already on product page) extended to category pages
- Wire SMTP for real alert emails

### v1 — differentiators
- LLM disambiguation queue for titles the regex can't parse
- Total-cost calculator (county + payment method)
- Counterfeit/lowball flag from price history
- Category expansion: tablets → laptops → TVs → home appliances → groceries

### v2 — scale + monetise
- Merchant self-serve dashboard (CPC bidding, featured placements)
- AdSense
- WhatsApp/Instagram informal-seller ingestion
- PWA polish
- Optional AI conversational search

## 10. Risks to actively manage

| Risk | Mitigation |
|---|---|
| Scrapers get blocked | Polite client (UA, delay, retry). Plan to add residential proxies if needed. Keep Playwright as fallback. |
| Stale prices erode trust | Show "last checked X ago" on every offer. Alert if a merchant hasn't updated in >24h. |
| Legal — ToS scraping | Public price scraping is generally defensible. Don't republish product copy verbatim; always link out; honour robots where reasonable. |
| Product matching errors | Track matched-without-confidence rate. Manual review queue from v0.5. |
| Free-tier limits | GitHub Actions cap → batch scrapes. Render cold starts → acceptable for v0; cache aggressively. |
| Affiliate program changes | Don't depend on a single program — Kilimall + AdSense as second/third revenue legs. |

## 11. Where the canonical research lives

- This file is the canonical doc.
- Memory: `~/.claude/projects/-Users-simonmuia/memory/project_kenya_price_comparison.md` and `reference_pricekenya_context_doc.md` point here.
- External sources (used 2026-06-30): wecantrack.com on comparison-site revenue, Avecdo on Prisjakt feeds, mybigorder.com on Kenyan online stores, kwetucollections.co.ke on Jumia vs Kilimall, trade.gov Kenya eCommerce guide, Statista eCommerce Kenya.
