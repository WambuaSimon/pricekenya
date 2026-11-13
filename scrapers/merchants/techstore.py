"""Tech Store Kenya (techstore.co.ke) — WooCommerce.

Large catalog (~279 pages / ~1000+ products at per_page=1). Store API
open. Their brand-specific slugs (`hp-laptops`, `dell-laptops`,
`apple-macbooks`) are already in UNIVERSAL_CATEGORY_MAP, so no
overrides needed.

2026-11-09: bot posture escalated past the default `cffi` client — every
scheduled run since logs `[wc-store] techstore-ke page1 GET failed:
RetryError: RetryError[<Future ... raised HTTPError>]` (curl_cffi's own
HTTPError, meaning Chrome TLS impersonation is being rejected outright,
not a network-layer drop). Same escalation pattern as jojabo-ke and
quickmart-ke hit around the same week — moved to playwright-stealth.
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
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        client_type="playwright-stealth",
    ):
        yield r
