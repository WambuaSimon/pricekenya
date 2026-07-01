# PriceKenya — Project Context

The canonical document for *why* this project exists, *what* it is, and *how* decisions were made. Update this when you learn something material — it's how future-you (and any agent) gets up to speed without re-doing research.

Last updated: 2026-07-01

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
