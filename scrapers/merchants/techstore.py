"""Tech Store Kenya (techstore.co.ke) — WooCommerce.

Large catalog (~279 pages / ~1000+ products at per_page=1). Store API
open. Their brand-specific slugs (`hp-laptops`, `dell-laptops`,
`apple-macbooks`) are already in UNIVERSAL_CATEGORY_MAP, so no
overrides needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "techstore-ke",
    "name": "Tech Store Kenya",
    "base_url": "https://techstore.co.ke",
}


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"], MERCHANT_META["slug"]
    ):
        yield r
