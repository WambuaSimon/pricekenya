"""Newmatic Kenya (newmatic.com) — WooCommerce.

Built-in kitchen appliances specialist: hobs, ovens, extractor hoods,
built-in fridges + dishwashers. About 25 categories, 171 pages via
Store API.

The catalog also contains "kitchen hardware" (sinks/taps, countertops,
splashbacks, LED cabinet lights, utensils) that don't map to any
PriceKenya leaf — those categories aren't in UNIVERSAL_CATEGORY_MAP so
they're silently dropped, which is the right behavior. If the user
wants to catalog those later they'd need a new leaf added upstream.

Hoods (extractor-hood-collection, wall-mounted-hoods, slim-hoods,
island-hoods) are ambiguous: they belong to the cooking category
in retail but PriceKenya doesn't have a "hoods" leaf yet. Routing
them to `cooking` for now — reconsider once we get a real hood leaf.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "newmatic-ke",
    "name": "Newmatic Kenya",
    "base_url": "https://newmatic.com",
}

# Merchant-specific overrides: newmatic's hood categories map to cooking
# until we have a proper hoods leaf. Everything else piggybacks on the
# universal map.
_OVERRIDES = {
    "extractor-hood-collection": "cooking",
    "wall-mounted-hoods": "cooking",
    "slim-hoods": "cooking",
    "island-hoods": "cooking",
    "pro-series": "cooking",  # PRO Series is oven / hob mix per their site
}


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        override_category_map=_OVERRIDES,
    ):
        yield r
