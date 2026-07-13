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
            "name": "Samsung BrandCart Kenya",
            "base_url": "https://samsung.brandcart.co.ke",
        },
    },
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
