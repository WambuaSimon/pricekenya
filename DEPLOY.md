# Deploy runbook

Everything in this file is a click-through that requires *your* accounts — I can't do it for you.

Order matters: **Render Postgres → Render web → GitHub Actions secret → seed prod DB**.

## 1. Render Postgres

Same provider and region as the web service, so app→DB traffic stays on
Render's private network. (We ran on Neon until 2026-10-04; see
OPERATIONS.md §8w for why we left.)

1. **New → Postgres**. Name `pricekenya-postgres`.
2. **Region must be `frankfurt`** — matching the web service is what makes
   the internal URL usable. Region, Postgres major version, database name
   and user are all **immutable after creation**; getting them wrong means
   a new instance and another migration.
3. Plan `basic_256mb`, Postgres **18**, disk **5 GB**. Allowed disk sizes are
   1 GB or multiples of 5; `pricehistory` grows ~11.6k rows/day with no
   pruning, disk **cannot shrink** once grown, and an over-limit database
   can be suspended — so don't start at 1 GB to save $1.20.
4. **Set the IP allow list to `0.0.0.0/0`** (Info → Access Control). The
   dashboard applies this by default but the **API does not** — a database
   created via API/MCP comes up with an empty list, which blocks *all*
   external access: `pg_dump`, `psql`, GUI clients, the Render MCP query
   tool, and GitHub Actions. Your web service is unaffected either way
   because it uses the internal URL.
5. Note both connection strings from the Info page. You need **both**, and
   they are not interchangeable:
   - **Internal** (`postgresql://...@dpg-xxx/dbname`) → the web service.
     Private network, no TLS overhead, lower latency.
   - **External** (`postgresql://...@dpg-xxx.frankfurt-postgres.render.com/dbname`)
     → GitHub Actions and local tooling, which sit outside Render. TLS required.

You can paste either verbatim. `app/config.py` normalises any Postgres
scheme to `postgresql+psycopg://`, because `psycopg2` is not installed and
SQLAlchemy would otherwise pick it for a bare `postgresql://` URL and die at
import. Don't hand-edit the scheme — that's the setting's job now.

## 2. Render (free web service)

1. Sign up: https://render.com (GitHub login).
2. **New → Blueprint** → point at the `pricekenya` repo. Render will read `render.yaml`.
3. It'll ask for the two `sync: false` values:
   - `DATABASE_URL` → the **internal** string from step 1
   - `JUMIA_AFFILIATE_ID` → leave empty for now (fill later once you sign up for Jumia's affiliate program)
4. Click deploy. First build ~3 min. Health check runs against `/healthz`.
5. Site is now live at `https://pricekenya.onrender.com`.

## 3. Add the DB secret to GitHub Actions

Actions needs `DATABASE_URL` to run the cron scrape — the **external**
string, not the internal one the web service uses. CI runners are outside
Render, so the internal `dpg-*` host does not resolve for them.

One secret covers `scrape.yml`, `sitemap.yml` and `reset-db.yml`.

```bash
# Pipe from a file rather than echoing the URL into your shell history.
gh secret set DATABASE_URL --repo WambuaSimon/pricekenya < /path/to/url.txt
```

Or via UI: repo → Settings → Secrets and variables → Actions → New repository secret.

## 4. First-run seed of the prod DB

Once the database has the schema (auto-created on first app boot via `init_db()`), kick off the first scrape so the site isn't empty:

```bash
gh workflow run scrape.yml --repo WambuaSimon/pricekenya
```

Or just wait — the cron will fire within 6 hours.

## 5. Google Search Console

- Add `https://pricekenya.onrender.com` as a property.
- Submit sitemap: `https://pricekenya.onrender.com/sitemap.xml`.
- SEO clock starts. Expect real traffic in 4–8 weeks if content is decent.

## 6. Health checks after deploy

```bash
curl https://pricekenya.onrender.com/healthz            # → ok
curl https://pricekenya.onrender.com/robots.txt         # → sitemap line points at your URL
curl -s https://pricekenya.onrender.com/sitemap.xml | grep -c '<url>'   # → 100+ after first scrape
```

## Schema migrations (one-shot, until Alembic)

We add Alembic when we have user data worth preserving. Until then, schema
changes that add columns to existing tables need a wipe-and-recreate:

```bash
DATABASE_URL="postgresql+psycopg://..." python -m db.reset --confirm
gh workflow run scrape.yml --repo WambuaSimon/pricekenya
```

The wipe is destructive by design — it exists only so v0 iteration isn't
blocked by migration ceremony. Grep the repo for `db.reset` before running to
be sure that's still true.

## Common failure modes

- **Render build fails on `pip install -e .`** — usually a Python version mismatch. `PYTHON_VERSION` is pinned in `render.yaml`; if you change it locally, keep them in sync.
- **`ModuleNotFoundError: psycopg2`** — a bare `postgresql://` URL reached SQLAlchemy without going through `app.config`. `pyproject.toml` pins `psycopg[binary]` (psycopg3); psycopg2 is not installed. The `Settings.database_url` validator normalises this, so suspect any code path building an engine from a raw env var instead of `settings`.
- **Connection refused / timeout from CI or a local client, but the site is fine** — the database's IP allow list is empty or too narrow. It gates *external* access only, which is exactly what CI and your laptop use. Set `0.0.0.0/0`.
- **`could not translate host name "dpg-..."`** — the **internal** URL used from outside Render. Switch that consumer to the external string.
- **Actions cron doesn't fire** — GitHub disables scheduled workflows on repos with no activity for 60 days. Push any commit to re-enable.
- **Site shows no products** — first cron scrape hasn't run yet. `gh workflow run scrape.yml`.

## Cost sanity check (as of setup)

| Piece | Cost |
|---|---|
| Render Postgres `basic_256mb` | $6/mo |
| Render Postgres disk, 5 GB @ $0.30/GB | $1.50/mo |
| Render web `starter` | $7/mo |
| GitHub Actions on public repo | $0 (unlimited minutes) |
| GitHub Actions on private repo | $0 up to 2000 min/month |

Database total: **$7.50/mo (~73 NOK)**, down from ~200 NOK on Neon — where
usage-metered compute sat pinned at the 0.25 CU floor because scale-to-zero
never fired for this traffic shape. OPERATIONS.md §8w has the measurements.
