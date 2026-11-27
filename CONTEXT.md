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
| DB | **SQLite (dev) → Render Postgres (prod)** | Schema kept portable, which is what made the 2026-10-04 move off Neon a `pg_dump`/`pg_restore` (OPERATIONS.md §8w). |
| Scraping | **httpx + selectolax** for static; **Playwright** as an opt-in extra | Selectolax is *fast* — important when scraping a few thousand pages/day on a free-tier VM. Playwright only when needed (JS-only renders, anti-bot checks). |
| Matching | Deterministic regex + slug canonical key; LLM hook left open | Cheap, debuggable, covers majority of titles. |
| Scheduling (dev) | APScheduler | Works in-process. |
| Scheduling (prod) | **GitHub Actions cron** | Free 2000 min/mo, no infra. |
| Hosting | **Render (web + DB) + GitHub Actions (cron)** | Co-locating the DB with the web service in Frankfurt keeps app→DB traffic on Render's private network and allows a real connection pool. ~$13.50/mo all-in; Oracle Cloud Always Free is the upgrade path if we outgrow Render. |
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

## 8. Operations log — moved out of this repo (2026-08-24)

Sections 8 through 8j (live-scrape learnings, merchant expansion, and the
2026-07/08 outage triages) now live in `OPERATIONS.md`, which `.gitignore`
excludes.

**That exclusion did not actually take effect until 2026-10-26.** The ignore
rule was added here on 2026-08-24, but `.gitignore` has no effect on a file
git is already tracking, and `OPERATIONS.md` was. So it kept being committed,
and every section written since — 8k through 8ag — was published to a public
repo. The file is untracked for real now. Note that untracking is not
erasure: every version committed before that date is still readable in this
repo's git history.

Why: that log records, merchant by merchant, which bot-mitigation each one
runs and exactly what defeats it — read next to the merchant names and base
URLs in `scrapers/config/`, it is a step-by-step guide for any merchant who
wants to lock us out. It is also what got this repo picked up by
proxy-vendor lead-gen scraping GitHub for "residential proxy".

Two things this move does NOT do, both deliberate:

  - It does not remove the material from git history. Every section is
    still readable in the public commit log unless that history is
    rewritten.
  - It does not cover the per-merchant comments in
    `scrapers/config/wc_merchants.py`, which explain the same escalations
    and fixes inline and remain public.

## 8ao. Scheduled triage — same seven legs, two new wrinkles, backlog now nineteen PRs (2026-11-27)

No `DATABASE_URL` in this environment; signal came entirely from the
`scrape.yml` matrix on GitHub Actions (`gh run view --json jobs` for
per-leg status, `gh api .../actions/jobs/<id>/logs` for log content — both
worked directly this pass, no `403` on the Azure blob redirect this time).

Covered the last 4 completed scheduled runs (`45576804817` → `45898455307`,
2026-11-25 08:30 → 2026-11-26 21:29 UTC).

**Every persistently-red leg this pass already has an open, clean,
mergeable PR against it, re-confirmed byte-for-byte against this pass's own
log pulls:**

| Leg | Signature this pass | Covered by |
|---|---|---|
| `all-quickmart` | `RetryError[HTTPError]` on `curl_cffi`, 4/4 runs | #115 (cffi → playwright-stealth) |
| `all-xiaomi` | `ScraperYieldTooLow`, zero diagnostic output, 4/4 runs | #129 (diagnostics-only; root cause still open by design) |
| `all-mybigorder` | `RetryError[HTTPStatusError]` on every one of 10 categories, plain httpx, 4/4 runs | #123 (`PoliteClient` → `CffiPoliteClient`) |
| `wc-pixels-ke` | Real HTTP 200, body is the host-level `<title>Website Suspended</title>` placeholder on every leaf, 4/4 runs | #121 (deprecate — hosting account suspended) |
| `wc-armco-ke` | Real HTTP 200, non-WooCommerce JS-rendered shell (no `wp-content`, no challenge markup) on every leaf, 4/4 runs; `kettles` again additionally threw `RetryError[HTTPStatusError]` on its second URL | #112 (diagnostic snippet widening only; no fix exists to open) |
| `wc-nextbuy-ke` | `RetryError[HTTPStatusError]` on the default `polite` client, 4/4 runs | #122 (cffi) |
| `naivas-ke` | Matrix leg green every run; `health` job's own table shows 255.5h stale, climbing from #130's 208.3h | #127 (diagnostics-only, unmerged) |

No new PR opened for any of the above — each is an (N+1)th corroboration of
a diagnosis that has already survived multiple independent re-verification
passes (most recently §8an/#130) with the signature unchanged. `wc-armco-ke`
still clears neither the TLS/JS-challenge playbook nor either deprecation
criterion; unchanged since §8u (2026-09-29).

**Wrinkle 1 — `wc-jojabo-ke` went green.** Red on every run since #108 was
opened (2026-11-05) straight through `45500663674` (2026-11-24 22:24,
confirmed via a 4-run back-check), then **green on the newest run**,
`45898455307` (2026-11-26 21:29) — the `health` job's table shows it
scraped successfully 0.2h before that job ran. This is exactly one data
point after weeks of red, the same "don't act on an unconfirmed recovery"
shape as `techstore-ke`'s self-recovery (flagged in #130, also confirmed
still holding this pass — 0.2h stale in the same `health` table). Not
closing #108/#111 on one green run; left a comment on #108 flagging the
recovery and asking whoever reviews next to re-check before merging a
`client_type` escalation the leg may no longer need.

**Wrinkle 2 — `wc-nairobilaptops-ke`, a new single-run failure with a
textbook signature.** Green on every run checked back through #130's
window, then failed once, on the newest run only (`45898455307`):

```
[wc] nairobilaptops-ke/audio page1 zero cards (status 200, body head): '<!DOCTYPE html> <html lang="en"> <head>   <meta charset="utf8">   ...
<script nonce="...">(function(){setTimeout(function(){window.location.reload();}, 5000);}('
```

— the JS-refresh bot-mitigation shell this codebase's playbook already has
a fix for (`client_type: "playwright-stealth"`, the housewife-ke/megatech-ke
pattern from §8j). One occurrence only, so per the standing megatech-ke
lesson (§8j — don't act on an unconfirmed single-run blip) this is **not**
acted on. Flagging the exact signature match so next pass doesn't have to
re-derive it from scratch if it recurs.

**The backlog, again.** `gh api repos/WambuaSimon/pricekenya/pulls?state=open`
returns **nineteen** open PRs (#107–#130), spanning 2026-10-31 through
2026-11-25. Nothing has merged since #105 on 2026-10-29 — **29 days, ~58
scheduled scrape runs** — with every fix sitting ready and unapplied the
entire time. §8an/#130 already laid out an ordered merge checklist
(deprecation first, then config-only escalations, then diagnostics-only,
with #118 flagged stale); this pass's only addition to that checklist is
that #108 should move to the "re-verify before merging" bucket alongside
#118, for the same reason. Not repeating the full checklist a sixth time.

`python3.13 -m pytest -q` — all tests pass. `python3.13 -m ruff check
scrapers/ tests/` — clean. No code change accompanies this write-up.

**Cross-check against the deprecation list.** No already-deprecated
merchant (7 Shopify, techonline-ke, zuka-ke, finetech-ke, overtech-ke,
nairobitvshop-ke, tclke-ke, smartdevices-ke, eamobitech-ke, audiocom-ke,
hisense-kenya-ke, sollatek-ke's stray row) produced any signal in this
window.

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

## 13. Tier 1 AI matching — implementation (shipped 2026-07-07)

Both phases landed dark (feature flags default false) covering all 16 category
slugs — the 14 with regex parsers plus the two orphaned scraper-only slugs
`freezers` and `water-dispensers` (100% drop → LLM-only recovery).

**Decisions taken vs §12:**
- Model: **Gemini 2.0 Flash** (free tier, 1500 req/day, native `response_schema` JSON output). Chosen over Haiku 4.5 to avoid needing a paid API account for v1.
- **Both phases shipped together.** The embedding merge in Phase 1 also protects against LLM-composer drift from the regex parsers.
- Embeddings: **MiniLM (`sentence-transformers/all-MiniLM-L6-v2`)** as an OPTIONAL dep (`pyproject.toml [embeddings]`). Web tier never imports `sentence_transformers` — enforced via `matching.embeddings.ALLOW_ENCODE` flag flipped only by scraper/CLI entrypoints. A dedicated web-isolation test guards this invariant.

**New surface area:**
- `matching/compose_keys.py` — one `compose_<slug>` per category. Same key format as the regex parser for that slug. LLM-parsed and regex-parsed products merge on identical canonical_keys.
- `matching/llm_extract.py` — Pydantic response schema per slug, ThreadPoolExecutor-wrapped Gemini call with a 3s timeout, DB-cache dedup via `title_hash`, per-category daily cap read from `LlmExtractionLog`.
- `matching/embeddings.py` — lazy MiniLM loader; `encode`, `cosine`, `find_nearest`; naive O(N) scan over same-category products (move to pgvector when a category >50k or p95 >100ms).
- `db/models.py` gained `LlmExtractionLog`, `ProductMergeCandidate`, `Product.embedding` (blob).
- `scripts/backfill_embeddings.py` — one-shot batch embed for existing products.
- `app/routes/admin.py` + `templates/admin/merge_review.html` — X-Admin-Key gated `/admin/merge-review` for 0.90–0.95 cosine candidates.
- Test suite: `tests/test_compose_parity.py` (guards drift), `tests/test_llm_extract.py`, `tests/test_match_llm_fallback.py`, `tests/test_embeddings.py`, `tests/test_admin_merge_review.py`. 213 pass, 1 skipped (embeddings, needs the extra installed).

**How to flip on:**
1. `LLM_FALLBACK_ENABLED=true` + `GEMINI_API_KEY=...` for Phase 0.
2. `pip install -e '.[embeddings]'` on the scraper worker, then `EMBEDDING_ENABLED=true`.
3. `python -m scripts.backfill_embeddings --category phones` to seed vectors.
4. `ADMIN_KEY=<secret>` to open the review page; browse to `/admin/merge-review` with `X-Admin-Key` header.

**Cost math to watch (Phase 0):** free-tier Gemini 2.0 Flash is 1500 req/day. `llm_daily_cap_per_category` default 500 across 16 slugs = 8000 potential/day, well under any single-project quota. If we approach the cap in prod, the natural next step is prompt caching or moving to a paid tier.

## 13. Security advisories assessed

A dated record of upstream advisories we checked this project against, so a
later reader can tell "were we affected by X?" without redoing the work.

### 2026-10 — eMudhra intermediate CA compromise; Node.js and PHP releases

Prompted by Render's 2026-10-23 customer notice covering three advisories.

| Advisory | Verdict |
|---|---|
| PHP2Shell | Not affected — no PHP, no Docker image in this repo. |
| Node.js TLS hostname bypass + Brotli RCE | Not affected — no Node runtime; the web service is the native Python runtime. GitHub's own Actions runner executes Node-based actions, which is GitHub-managed, not ours. |
| eMudhra / emSign intermediate CA key compromise | **Was affected, via `certifi`. Fixed.** |

**Why eMudhra reached us.** Eight eMudhra intermediates had recoverable
private keys. They chain to four roots; exactly one of those — `emSign ECC
Root CA - G3`, a cross-signer — was present in the `certifi` bundle this
project installs. Because Python's HTTP clients trust `certifi` rather than
the OS store, every outbound HTTPS call inherited that trust. The widely
reported Sectigo cross-sign path did **not** apply: it chains to `AAA
Certificate Services`, which Mozilla had already dropped, so it was never in
our bundle. `emSign Root CA - G1` is still in `certifi` and that is correct —
it did not issue the compromised intermediates and must not be stripped.

**Fix.** `certifi>=2026.10.19` is the first bundle to drop the affected root;
the floor is now explicit in `pyproject.toml`. There is no lockfile, so every
build re-resolves — which is exactly why the floor is written down rather than
left to `curl_cffi`'s transitive requirement.

**Both HTTP clients are covered, for different reasons.** `httpx` reads
`certifi` directly. `curl_cffi` prefers `ssl.get_default_verify_paths()` and
only falls back to `certifi`, so on a host whose Python ships its own OpenSSL
CA file it will silently use that instead — a store `pip` cannot update. On the
Linux runtime that path is the distro store, refreshed when the service
rebuilds.

**Provenance note.** The `pyproject.toml` floor was committed by accident
inside #93 ("Cache product images in R2"), an unrelated PR, rather than under
its own change. The pin itself is correct and was verified in a production
build; only its attribution is wrong. This section is the audit trail that
commit should have carried.
