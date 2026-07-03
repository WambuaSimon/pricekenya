"""iStore Kenya (istore.ke) scraper — WooCommerce.

Apple official reseller. Catalog is narrow (Apple only) but adds authoritative
pricing baselines for iPhone/iPad/MacBook/Watch that other merchants can be
compared against.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.woocommerce import fetch_woocommerce_category

MERCHANT_META = {
    "slug": "istore-ke",
    "name": "iStore Kenya",
    "base_url": "https://istore.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
BASE = MERCHANT_META["base_url"]

LEAF_TO_URL: dict[str, str] = {
    "phones":  f"{BASE}/product-category/iphone/",
    "tablets": f"{BASE}/product-category/ipad/",
    "laptops": f"{BASE}/product-category/macbooks/",
}


async def _one(leaf: str) -> AsyncIterator[RawListing]:
    async for r in fetch_woocommerce_category(
        LEAF_TO_URL[leaf], 3, MERCHANT_SLUG, leaf, BASE
    ):
        yield r


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _one("phones"):
        yield r


async def fetch_tablets() -> AsyncIterator[RawListing]:
    async for r in _one("tablets"):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _one("laptops"):
        yield r
