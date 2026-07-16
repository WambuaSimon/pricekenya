"""Patabay Kenya (patabay.co.ke) — WooCommerce.

Was previously left out of the wc_batch config because their theme
hides prices on category cards. Store API delivers prices directly,
so patabay is unblocked.

Big catalog: ~1,272 pages via Store API. Categories are extremely
noisy (marketing groupings like "large-home-appliances",
"home-appliances", "home-and-living-appliances", brand-only slugs,
etc.) but the products themselves also carry specific sub-category
slugs (`fridges`, `laptop`, `theater`) that UNIVERSAL_CATEGORY_MAP
picks up. Anything routing to nothing is silently dropped.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "patabay-ke",
    "name": "Patabay Kenya",
    "base_url": "https://patabay.co.ke",
}

# Patabay uses `theater` as a top-level bucket that mixes home theater
# systems AND some AV accessories. Their `laptop` (singular) is another
# quirk. Both are in UNIVERSAL_CATEGORY_MAP so no override needed.
# Cap max_pages higher because their catalog is genuinely big.


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        max_pages=60,  # per_page=100 × 60 = 6k products ceiling
    ):
        yield r
