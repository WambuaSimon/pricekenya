# PriceKenya — Project Context

The canonical document for *why* this project exists, *what* it is, and *how* decisions were made. Update this when you learn something material — it's how future-you (and any agent) gets up to speed without re-doing research.

Last updated: 2026-07-07

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

## 9. Roadmap

### v0.5 — make it production-credible
- Real scrapers for Kilimall, Phone Place, Avechi, Safaricom Shop
- Click logging (`out/{listing_id}` → write a Click row before redirect) for revenue attribution
- robots.txt + sitemap.xml generated from DB
- JSON-LD `AggregateOffer` (already on product page) extended to category pages
- Wire SMTP for real alert emails

### v1 — differentiators
- LLM disambiguation queue for titles the regex can't parse (see §12 for the plan)
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

## 12. Tier 1 AI matching — plan (2026-07-07)

Framing: of every AI feature we could bolt on, cross-merchant matching is the only one that's actually a moat. Chatbot / conversational search / recommendations either won't move the needle at Kenyan buyer intent or will be eaten by Google's AI Overviews. Matching compounds — every extra merchant match makes every product page more valuable, which strengthens SEO, which brings more traffic, which makes the next matching improvement more valuable.

### 12.1 What we have today

- 14 category parsers in `matching/*.py` (~2,700 LOC). Each extracts brand/model/specs from a merchant title via hand-tuned regex, produces `canonical_key = "brand|model|storage|ram"`, and inserts into `Product`.
- Deterministic string-equality merge via `canonical_key`.
- Silent drop at `matching/match.py:39` when the regex fails (`# v1 hook: drop into LLM disambiguation queue. For v0, just skip.`).

### 12.2 Concrete gaps

| Gap | Cost today |
|---|---|
| Regex-fail listings are dropped silently | Lost merchant coverage every scrape. Directly hurts value prop and SEO signal. |
| `canonical_key` string-equality is brittle | Any brand-alias miss (e.g. "Apple iPhone 16" vs "iPhone 16") splits one product into two → fragments price data, weakens ranking, splits history. |
| New category = 200-350 LOC hand-tuned parser | Coverage grows slowly. Every category rollout is a project, not a config change. |
| No confidence signal from the parser | "Matched" is binary. No way to flag "parsed but suspicious" (e.g. two `128GB` mentions) for review. |

### 12.3 Phase 0 — LLM fallback for extraction failures

Replace the silent drop at `match.py:39` with a Claude Haiku 4.5 call.

- New module `matching/llm_extract.py`, one function `extract(title, category) -> ParsedTitle | None`.
- Structured output — JSON schema per category, mirrors `ParsedTitle.specs`. Forces Haiku to return only fields that exist.
- Result flows back through the existing `canonical_key` construction; nothing downstream changes.
- New table `LlmExtractionLog(title, category, response, latency, cost_usd, created_at)`. Every call logged. Turns the fallback into a free evaluation dataset.
- Guardrails: 3s timeout; per-category rate limit (broken scraper can't blow up the bill); title-hash cache (same title from three merchants = one LLM call); prompt-cache the system prompt (~90% cost cut on repeat calls).
- On failure (timeout, 5xx, unparseable JSON) → drop as today. Never worse than the status quo.

**Cost math** (rough): assume ~100k listings/month ingested, ~10% currently regex-fail. That's ~10k LLM calls/month at ~400 input + 100 output tokens each. Haiku 4.5 at ~$1/M input, ~$5/M output → **~$0.90/month**. With prompt caching, **~$0.30/month**. Even 10× volume stays under $10/month.

**Success metric:** count of listings that used to be dropped but now attach to a Product. Reported weekly. If <1% of ingested volume, we rip it out cheaply.

### 12.4 Phase 1 — embedding-based reconciliation

Only after Phase 0 has a month of data.

- Add `Product.embedding` (blob, 384-dim float32) using `sentence-transformers/all-MiniLM-L6-v2`. Free, CPU, ~10ms per title.
- Before creating a new Product: compute embedding, find nearest neighbor in same `category_slug`. If cosine > 0.90 and `canonical_key` differs → merge candidate. Auto-merge at >0.95, review queue for 0.90–0.95.
- Catches the "same product, different canonical_key" bug class (brand aliases, alt spellings, spacing differences).
- Storage: SQLite blob column is enough at current scale. Switch to pgvector when we migrate to Postgres.
- Side benefit: Related Products (shipped 2026-07-07, currently sorted by absolute price distance) can switch to embedding cosine for smarter "similar" — better UX, better internal linking.

Cost: zero API. One-time bulk-embed of existing products (~2k rows × 10ms = 20s). Adds ~10ms to ingest latency per listing.

### 12.5 Phase 2 — replace category parsers entirely (contingent)

Only if Phase 0 shows LLM extraction quality matches or beats regex parsers head-to-head on a labelled sample. If it does, swap `_PARSERS` entries in `matching/match.py:30` to point at the LLM extractor. Adding a new category becomes a one-line schema entry.

Do not do this speculatively. Regex parsers are fast, deterministic, and free — the LLM has to earn the replacement.

### 12.6 Explicitly not proposing

- No vector DB (Pinecone / Weaviate). sqlite-vec or a blob column is enough.
- No fine-tuning. Off-the-shelf embeddings + a small LLM cover this cleanly.
- No chatbot / natural-language search / recommender. Different rabbit holes, different ROI curve.
- No ripping the ingest architecture. Everything slots into the existing `matching/match.py` shape.

### 12.7 Risks

| Risk | Mitigation |
|---|---|
| LLM hallucinates a spec that doesn't exist | Structured output + per-category JSON schema + every call logged for review. |
| Anthropic API outage | Ingest drops the listing exactly like today. No worse than v0. |
| Cost surprise from a broken scraper | Per-category rate limit + hard daily cap in the Anthropic dashboard. |
| Wrong auto-merge in Phase 1 | Conservative auto threshold (0.95+). 0.90–0.95 goes to a review inbox until we trust it. |

### 12.8 Open decisions

1. **Model:** Claude Haiku 4.5 (default — same ecosystem as Claude Code, first-class structured output) or Gemini Flash / GPT-4o-mini?
2. **Phase 0 scope:** just the LLM fallback, or bundle Phase 1 embeddings in the first PR? Default: ship Phase 0 alone. A month of data tells us whether Phase 1 is even needed.
