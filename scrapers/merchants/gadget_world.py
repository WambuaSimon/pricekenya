"""Gadget World Kenya (gadgetworld.co.ke) scraper — WooCommerce.

Computing-heavy specialist: laptops, monitors, printers, storage, desktops,
networking equipment. Their site advertises Brother printers heavily —
useful for the /c/computing bucket where Jumia/Kilimall are thin.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.woocommerce import fetch_woocommerce_category

MERCHANT_META = {
    "slug": "gadget-world-ke",
    "name": "Gadget World Kenya",
    "base_url": "https://gadgetworld.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
BASE = MERCHANT_META["base_url"]

LEAF_TO_URL: dict[str, str] = {
    "laptops":  f"{BASE}/product-category/laptops/",
}


async def _one(leaf: str) -> AsyncIterator[RawListing]:
    async for r in fetch_woocommerce_category(
        LEAF_TO_URL[leaf], 3, MERCHANT_SLUG, leaf, BASE
    ):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _one("laptops"):
        yield r
