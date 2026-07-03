"""Avechi Kenya (avechi.co.ke) scraper — WooCommerce.

Domain migrated from avechi.com → avechi.co.ke; the WooCommerce structure is
unchanged. Category URL pattern is /product-category/<slug>/.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.woocommerce import fetch_woocommerce_category

MERCHANT_META = {
    "slug": "avechi-ke",
    "name": "Avechi",
    "base_url": "https://avechi.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
BASE = MERCHANT_META["base_url"]

LEAF_TO_URL: dict[str, str] = {
    "phones":         f"{BASE}/product-category/smartphones/",
    "laptops":        f"{BASE}/product-category/laptops/",
    "tvs":            f"{BASE}/product-category/tvs/",
    "audio":          f"{BASE}/product-category/audio/",
    "refrigerators":  f"{BASE}/product-category/fridges/",
    "cameras":        f"{BASE}/product-category/cameras/",
}


async def _one(leaf: str) -> AsyncIterator[RawListing]:
    async for r in fetch_woocommerce_category(
        LEAF_TO_URL[leaf], 3, MERCHANT_SLUG, leaf, BASE
    ):
        yield r


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _one("phones"):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _one("laptops"):
        yield r


async def fetch_tvs() -> AsyncIterator[RawListing]:
    async for r in _one("tvs"):
        yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    async for r in _one("audio"):
        yield r


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    async for r in _one("refrigerators"):
        yield r


async def fetch_cameras() -> AsyncIterator[RawListing]:
    async for r in _one("cameras"):
        yield r
