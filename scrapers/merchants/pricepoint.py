"""Price Point Kenya (pricepoint.co.ke) — WooCommerce Store API.

Was previously wired via wc-batch with HTML scraping and yielded 0 rows.
Their theme, like several others we've had to migrate, hides prices
from category cards — the Store API endpoint is enabled and public
(~893 pages via /wp-json/wc/store/v1/products), so this rewrite delegates
to the shared helper.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "pricepoint-ke",
    "name": "Price Point Kenya",
    "base_url": "https://www.pricepoint.co.ke",
}


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        max_pages=60,  # big catalog
    ):
        yield r
