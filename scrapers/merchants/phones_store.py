"""Phones Store Kenya (phonesstorekenya.com) — WooCommerce Store API.

Their theme was rebuilt in mid-2026 and the older HTML selectors we
depended on stopped matching anything (0-yield for weeks, caught by
the tightened min-yield guard on 2026-07-16). This rewrite uses the
public `/wp-json/wc/store/v1/products` endpoint, same shared helper
that powers xiaomi, finetech, techstore, patabay, newmatic.

Category routing goes through UNIVERSAL_CATEGORY_MAP by default plus a
small merchant-specific override map for slugs Phones Store uses that
aren't already in the universal set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "phonesstore-ke",
    "name": "Phones Store Kenya",
    "base_url": "https://phonesstorekenya.com",
}

# Merchant-specific slugs that aren't already in UNIVERSAL_CATEGORY_MAP.
# Extend as new categories appear in their /wp-json/wc/store/v1/products/
# categories response.
_OVERRIDES: dict[str, str] = {
    # Gaming consoles and controllers
    "gaming": "console-accessories",
    "gaming-accessories": "console-accessories",
    "consoles": "console-accessories",
    # Their broader accessory buckets
    "phone-cases": "phone-tablet-accessories",
    "screen-protectors": "phone-tablet-accessories",
    "smartwatches": "phone-tablet-accessories",
    "smart-watches": "phone-tablet-accessories",
}


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        override_category_map=_OVERRIDES,
    ):
        yield r


# ---------------------------------------------------------------------------
# Legacy per-category shims — kept so the existing runners in ingest.py and
# matrix legs in scrape.yml (all-phonesstore) don't need to change. Each
# yields nothing on its own; the single fetch_all above is what actually
# populates the merchant. See run_phonesstore() for the entry point that
# invokes fetch_all directly.
# ---------------------------------------------------------------------------


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "phones":
            yield r


async def fetch_tablets() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "tablets":
            yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "laptops":
            yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "audio":
            yield r


async def fetch_cameras() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "cameras":
            yield r


async def fetch_accessories() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "phone-tablet-accessories":
            yield r


async def fetch_console_accessories() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "console-accessories":
            yield r


async def fetch_gaming() -> AsyncIterator[RawListing]:
    async for r in fetch_all():
        if r.category_slug == "console-accessories":
            yield r
