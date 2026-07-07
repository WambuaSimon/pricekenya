"""Config for the Shopify-batch scraper.

Shopify stores all expose `/products.json` with the entire catalogue,
paginated at `?page=N&limit=250`. No discovery pass is needed — the
category routing happens inside `scrapers.common.shopify` (product_type
first, title-keyword fallback). Adding a Shopify merchant = one entry
here + no code change.
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
}
