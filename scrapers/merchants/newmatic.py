"""Newmatic Kenya (newmatic.com) — WooCommerce.

Built-in kitchen appliances specialist. As of 2026-07-17 covers hobs,
ovens, microwaves, extractor hoods, built-in fridges, built-in
dishwashers, coffee machines, sinks/taps, countertops, splashbacks,
kitchen hardware, utensils, and PRO-series product bundles — every
category on their site that maps to a PriceKenya leaf.

Two dispatch quirks:
- Hoods (extractor-hood-collection + slim/wall/island) route to `cooking`
  via _OVERRIDES since PriceKenya's cooking matcher now supports a
  `hood` type. Reconsider if we ever add a top-level `hoods` leaf.
- `small-kitchen-appliances` is a Newmatic-specific mixed bucket —
  coffee machines, small fridges, ice/cup dispensers, and power sockets
  all share the tag with no per-product sub-category. Route it to
  `_ska_pending` and dispatch by title (see `_dispatch_small_kitchen`).
  Items we can't classify (ice/cup dispensers today) drop silently.
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

_OVERRIDES = {
    # Hoods → cooking (matcher grew a `hood` type on 2026-07-17)
    "extractor-hood-collection": "cooking",
    "wall-mounted-hoods": "cooking",
    "slim-hoods": "cooking",
    "island-hoods": "cooking",
    # PRO Series is an oven / hob bundle line
    "pro-series": "cooking",
    # Mixed bucket — resolved per-title below.
    "small-kitchen-appliances": "_ska_pending",
}


def _dispatch_small_kitchen(title: str) -> str | None:
    """Newmatic's small-kitchen-appliances tag mixes families with no
    per-product sub-tags. Route by title keyword; return None to drop
    items we don't have a leaf for (ice/cup dispensers today)."""
    t = title.lower()
    if "coffee" in t or "espresso" in t or "cafetière" in t:
        return "coffee-machines"
    if "fridge" in t or "refrigerator" in t:
        return "refrigerators"
    if "socket" in t or " plug" in t or "power track" in t:
        return "kitchen-hardware"
    return None


async def fetch_all() -> AsyncIterator[RawListing]:
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        override_category_map=_OVERRIDES,
    ):
        # Newmatic titles carry only the SKU code — no brand token — e.g.
        # "H19.9S Undermount Chimney Slim Hood". Prefix the merchant name
        # so the matcher's brand check accepts it. Same trick as
        # ramtons/scrapers/merchants/ramtons.py::_extract.
        if "newmatic" not in r.title.lower():
            r.title = f"Newmatic {r.title}"

        if r.category_slug == "_ska_pending":
            leaf = _dispatch_small_kitchen(r.title)
            if not leaf:
                continue  # drop — no PriceKenya leaf for this SKU family
            r.category_slug = leaf

        yield r
