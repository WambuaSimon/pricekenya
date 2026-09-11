"""Solar Store East Africa (solarstore.co.ke) — WooCommerce.

Was previously scraped via wc_batch HTML parsing. As of 2026-08 the site's
theme/plugin stack throws a WordPress critical error on every frontend
page (`/`, `/shop/`, `/product-category/*/` all return HTTP 500 with the
"There has been a critical error on this website." template appended to
a half-rendered category page). The Store API endpoint
`/wp-json/wc/store/v1/products` still returns 200 with clean JSON, so
switching to it unblocks the scrape without waiting for the merchant to
fix their frontend.

Category routing:
  SolarStore uses solar-specific WC slugs that aren't in
  UNIVERSAL_CATEGORY_MAP. All the inverter families (solar-inverters,
  hybrid-inverters, off-grid, grid-tie, three-phase, MPPT/PWM controllers,
  water-pumping inverters, backup, inverter-chargers) route to `inverters`.
  Chemistry-specific battery slugs (lithium-batteries, lead-carbon,
  gel-batteries, lead-acid-battery) route to `solar-batteries`. SolarStore
  does not stock solar panels — everything else (water pumps, water heaters,
  outdoor lights, mounting hardware, combiner boxes, cables etc.) has no
  PriceKenya leaf and drops silently.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.wc_store_api import fetch_wc_store_catalog

MERCHANT_META = {
    "slug": "solarstore-ke",
    "name": "Solar Store East Africa",
    "base_url": "https://solarstore.co.ke",
}

# Solar-specialist slugs → PriceKenya leaves. Keep local — these are
# specific enough to SolarStore's catalog that dumping them into the
# universal map would risk misrouting on other merchants.
_OVERRIDES = {
    # Every inverter variant lives under `inverters`.
    "solar-inverters": "inverters",
    "hybrid-inverters": "inverters",
    "off-grid-inverter": "inverters",
    "grid-tie-inverters": "inverters",
    "inverter-chargers": "inverters",
    "backup-inverters": "inverters",
    "solar-water-pumping-inverters": "inverters",
    "three-phase": "inverters",
    # Charge controllers are inverter-adjacent power electronics — no
    # dedicated leaf on PriceKenya, so bucket with inverters.
    "mppt": "inverters",
    "pwm": "inverters",
    # Battery chemistries all roll up to the solar-batteries leaf.
    "lithium-batteries": "solar-batteries",
    "lead-carbon": "solar-batteries",
    "gel-batteries": "solar-batteries",
    "lead-acid-battery": "solar-batteries",
}


async def fetch_all() -> AsyncIterator[RawListing]:
    # 2026-09-09/10: every run failed `RetryError[HTTPError]` on curl_cffi's
    # own client (the default) across 4 straight scheduled runs
    # (33778433274 was the last green one; every run since has been red) —
    # a real HTTP error status even under Chrome TLS impersonation, not a
    # timeout. Same signature that already forced smartdevices-ke and
    # eamobitech-ke from cffi to playwright-stealth (OPERATIONS.md §8n),
    # and the same IP-reputation pattern patabay-ke/hisense-kenya-ke hit on
    # this same WC Store API path. See OPERATIONS.md §8o.
    async for r in fetch_wc_store_catalog(
        MERCHANT_META["base_url"],
        MERCHANT_META["slug"],
        override_category_map=_OVERRIDES,
        client_type="playwright-stealth",
    ):
        yield r
