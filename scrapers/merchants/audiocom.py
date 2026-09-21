"""Audiocom Kenya (audiocomkenya.co.ke) — WooCommerce Store API.

Pro-audio specialist. Was previously configured to scrape only the
amplifier URLs to `audio` via wc-batch (the wider catalog included DJ
controllers, digital mixers, MIDI keyboards etc. that the consumer-
electronics matchers reject). Store API is open (~1028 pages), so this
rewrite pulls everything and lets UNIVERSAL_CATEGORY_MAP + the accessory-
rejection guards in the category matchers do the routing / filtering.

Products the matcher can't route (specialty pro-audio gear) get
silently dropped — same behaviour as any other WC Store API merchant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "audiocom-ke",
    "name": "Audiocom Kenya",
    "base_url": "https://www.audiocomkenya.co.ke",
}


async def fetch_all() -> AsyncIterator[RawListing]:
    # Every leg failed `RetryError[HTTPError]` on curl_cffi's own client
    # (the default) in the 4 most recent scheduled runs checked, 2026-09-19
    # 04:35 -> 2026-09-20 16:04 (runs 35421722659 -> 35521557261) — a real
    # HTTP error status even under Chrome TLS impersonation, not a timeout.
    # Confirmed green as recently as 2026-09-16 04:47 (run 35056989837), so
    # this is a new escalation, not a standing issue. Same signature that
    # already forced smartdevices-ke/eamobitech-ke (§8n) and solarstore-ke
    # (§8o) from cffi to playwright-stealth. See OPERATIONS.md §8p.
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        max_pages=60,  # ~1028 pages via API — 60 × 100 = 6000 ceiling
        client_type="playwright-stealth",
    ):
        yield r
