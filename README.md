# PriceKenya

Price comparison for the Kenyan market — Jumia, Kilimall, Phone Place, Avechi, Safaricom Shop. Smartphones first.

See [CONTEXT.md](./CONTEXT.md) for market research, decisions, and roadmap.

## Stack
- **FastAPI** (Python) — single service, server-rendered Jinja templates.
- **HTMX + Alpine + Tailwind CDN** — interactivity without a build step.
- **SQLModel** on SQLite (dev) / Postgres (prod).
- **httpx + selectolax** for static-HTML scraping. **Playwright** is an optional extra for JS-heavy pages.
- **APScheduler** for local cron; **GitHub Actions** for free production cron.

## Run locally

```bash
cd ~/work/pricekenya
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Load merchants + sample products + 30 days of fake price history
python -m seed.load

# Serve
uvicorn app.main:app --reload
# → http://localhost:8000
```

Then visit `/` to browse, `/p/<slug>` for a product page, `/search?q=tecno` to search.

## Run the real scraper

```bash
python -m scrapers.ingest jumia-phones
```

It fetches the first 3 pages of `jumia.co.ke/smartphones`, parses listings, matches them to products by canonical key, and writes prices + history.

## Run the price-drop alert dispatcher

```bash
python -m alerts.dispatcher
```

v0 prints to stdout. Wire `SMTP_*` env vars to send real emails.

## Project layout

```
app/                 FastAPI app + Jinja templates + HTMX
  routes/            pages, products, alerts
  templates/         server-rendered HTML
db/                  SQLModel models + session
matching/            normalize titles, canonical key, match-or-create
scrapers/
  common/            polite HTTP client, RawListing dataclass
  merchants/         one file per merchant
  ingest.py          fetch → match → upsert + history
workers/             APScheduler local-dev runner
alerts/              price-drop dispatcher
seed/                merchants + sample products
```

## Deploy free-tier

| Piece | Provider |
|---|---|
| Web app | Render free web service (cold starts after 15min idle) |
| Postgres | Neon free tier |
| Cron / scrapers | GitHub Actions (2000 free min/mo) |

Set `DATABASE_URL` to the Neon connection string. Use a GitHub Action that runs `python -m scrapers.ingest jumia-phones` on a schedule.

## What's intentionally not here yet
- LLM-based product matching for unparseable titles (hook is in `matching/match.py`)
- User accounts beyond email-only alerts
- Reviews aggregation
- Total-cost calculator (delivery + M-Pesa fees)
- More merchants (Kilimall, Phone Place, Avechi, Safaricom Shop — only Jumia is wired)
- Ads / affiliate tracking dashboard

These are listed in [CONTEXT.md](./CONTEXT.md) under "Roadmap".

## License

[AGPL-3.0-or-later](./LICENSE). If you run a modified version of this code as a public network service, you must publish the modified source under the same license. See [gnu.org/licenses/agpl-3.0](https://www.gnu.org/licenses/agpl-3.0.html) for the full terms.
