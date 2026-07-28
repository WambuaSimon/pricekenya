"""Config for the Shopify-batch scraper.

Shopify stores all expose `/products.json` with the entire catalogue,
paginated at `?page=N&limit=250`. No discovery pass is needed — the
category routing happens inside `scrapers.common.shopify` (product_type
first, title-keyword fallback). Adding a Shopify merchant = one entry
here + no code change.

STATUS (2026-07-28): every merchant below is currently un-scrapable from
CI. GitHub Actions Azure IPs get HTTP 429 `local_rate_limited` from
Shopify's edge, and Render's Frankfurt IP is also rate-limited (shared
DC IP pool with heavy scrapers). Local KE residential IPs still work,
so the code + selectors are fine — it's an IP-reputation problem.
Deferred until we justify a residential proxy service (Path B in the
2026-07-28 outage triage). See CONTEXT.md §8g for the full decision log.
The `/internal/scrape/{target}` endpoint (app/routes/internal.py) is
still in place so a future proxy client can be dropped in without
rewriting the trigger.
"""

from __future__ import annotations

SHOPIFY_MERCHANTS: dict[str, dict] = {
    "digitalcity-ke": {
        "meta": {
            "slug": "digitalcity-ke",
            "name": "Digital City Electronics",
            "base_url": "https://www.digitalcityelectronics.com",
        },
    },
    "zentech-ke": {
        "meta": {
            "slug": "zentech-ke",
            "name": "Zentech Electronics",
            "base_url": "https://zentechelectronics.com",
        },
    },
    "digitalstore-ke": {
        "meta": {
            "slug": "digitalstore-ke",
            "name": "Digital Store",
            "base_url": "https://www.digitalstore.co.ke",
        },
    },
    "samsung-brandcart-ke": {
        "meta": {
            "slug": "samsung-brandcart-ke",
            "name": "BrandCart Kenya",
            # Original recon pointed at the samsung.* subdomain which serves
            # zero products via /products.json (the real catalog lives at
            # the root apex). Kept the slug for DB continuity with the row
            # that was seeded before this fix.
            "base_url": "https://brandcart.co.ke",
        },
    },
    # sollatek-ke intentionally NOT added:
    #   - Their Shopify store shop.sollatek.com sells voltage guards /
    #     surge protectors (Fridgeguard, Notebook Guard etc.), not consumer
    #     electronics. Products like "FGIN Fridgeguard 230V 5A" don't fit
    #     PriceKenya's taxonomy.
    #   - Prices on the Shopify /products.json feed look wholesale-tier
    #     (KSh 19.89 for a Fridgeguard = not a retail figure). Even if we
    #     shipped a "power-protection" leaf, the numbers wouldn't help
    #     shoppers.
    #   - Their consumer-facing solar catalog we hoped for lives on
    #     sollatek.co.ke as a marketing site, no e-commerce data.
    "laptopclinic-ke": {
        "meta": {
            "slug": "laptopclinic-ke",
            "name": "Laptop Clinic Kenya",
            "base_url": "https://laptopclinic.co.ke",
        },
    },
    "vividgold-ke": {
        "meta": {
            "slug": "vividgold-ke",
            "name": "Vivid Gold (Video Game Outlet)",
            "base_url": "https://vividgold.co.ke",
        },
    },
    "badili-ke": {
        "meta": {
            "slug": "badili-ke",
            "name": "Badili Kenya",
            "base_url": "https://badili.ke",
        },
    },
}
