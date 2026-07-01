# Deploy runbook

Everything in this file is a click-through that requires *your* accounts — I can't do it for you.

Order matters: **Neon → Render → GitHub Actions secret → seed prod DB**.

## 1. Neon Postgres (free tier)

Neon gives you a real Postgres URL with no expiry (unlike Render's 30-day-expiring free DB).

1. Sign up: https://neon.tech (GitHub login works).
2. Create project → name it `pricekenya`. Region: pick whatever is closest to Frankfurt (Render's region). `Europe (Frankfurt)` is ideal if listed.
3. Copy the **pooled** connection string. It looks like:
   ```
   postgresql://user:pass@ep-xxx.pooler.eu-central-1.aws.neon.tech/pricekenya?sslmode=require
   ```
4. Replace `postgresql://` with `postgresql+psycopg://` so SQLAlchemy uses the psycopg3 driver we already have installed. Save this — you'll paste it into Render and GitHub next.

## 2. Render (free web service)

1. Sign up: https://render.com (GitHub login).
2. **New → Blueprint** → point at the `pricekenya` repo. Render will read `render.yaml`.
3. It'll ask for the two `sync: false` values:
   - `DATABASE_URL` → the Neon string from step 1
   - `JUMIA_AFFILIATE_ID` → leave empty for now (fill later once you sign up for Jumia's affiliate program)
4. Click deploy. First build ~3 min. Health check runs against `/healthz`.
5. Site is now live at `https://pricekenya.onrender.com`. Cold starts after 15 min idle — acceptable for v0.

## 3. Add the DB secret to GitHub Actions

Actions needs the same `DATABASE_URL` to run the cron scrape.

```bash
gh secret set DATABASE_URL --repo WambuaSimon/pricekenya
# paste the Neon URL when prompted
```

Or via UI: repo → Settings → Secrets and variables → Actions → New repository secret.

## 4. First-run seed of the prod DB

Once Neon has the schema (auto-created on first app boot via `init_db()`), kick off the first scrape so the site isn't empty:

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

## Common failure modes

- **Render build fails on `pip install -e .`** — usually a Python version mismatch. `PYTHON_VERSION` is pinned in `render.yaml`; if you change it locally, keep them in sync.
- **`sslmode=require` errors** — Neon requires SSL. The connection string already has `?sslmode=require`. If you built the URL yourself, add it.
- **Actions cron doesn't fire** — GitHub disables scheduled workflows on repos with no activity for 60 days. Push any commit to re-enable.
- **Site shows no products** — first cron scrape hasn't run yet. `gh workflow run scrape.yml`.

## Cost sanity check (as of setup)

| Piece | Cost |
|---|---|
| Neon free tier | $0 (3GB storage cap) |
| Render free web | $0 (spins down after 15min idle) |
| GitHub Actions on public repo | $0 (unlimited minutes) |
| GitHub Actions on private repo | $0 up to 2000 min/month |
| Domain (deferred) | ~$12/yr when you're ready |

Total: **$0/mo** until you outgrow one of the free tiers.
