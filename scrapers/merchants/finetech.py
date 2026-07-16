"""Finetech Kenya (finetech.co.ke) — WooCommerce.

Small catalog (~17 categories, ~90 products). Public Store API is
enabled, so this scraper is a one-liner delegating to the shared
helper. Category slugs match UNIVERSAL_CATEGORY_MAP directly — no
merchant-specific overrides needed.

Was previously wired via wc_batch with HTML scraping but yielded zero
rows: their WC theme was one of the ones that hides prices from category
cards. Store API bypasses that entirely.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "finetech-ke",
    "name": "Finetech",
    "base_url": "https://finetech.co.ke",
}


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"], MERCHANT_META["slug"]
    ):
        yield r
