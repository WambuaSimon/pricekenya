"""Hotpoint Kenya scraper.

Hotpoint runs a Next.js frontend on a Shopify backend. Category pages don't
render product prices in the initial HTML — they're loaded client-side. But
the pages DO embed a JSON-LD ItemList schema listing all products' names +
URLs, and each product detail page embeds a JSON-LD Product schema with the
real price. So the scrape is a two-step fetch:

1. GET category page → parse escaped ItemList in Next.js flight data →
   list of (name, product_url) pairs
2. GET each product URL → parse JSON-LD Product → price + image

Known limits:
- Hotpoint's ItemList caps at 53 items even when productCount is higher.
  The tail is loaded client-side via JS infinite-scroll which we don't run.
  ~80% coverage per category is acceptable for v0.
- Detail-page fetches are the expensive step; per-category cost is
  approximately 53 × 2s (polite delay) ≈ 2 minutes.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "hotpoint-ke",
    "name": "Hotpoint Kenya",
    "base_url": "https://hotpoint.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

# Our leaf category slug → list of Hotpoint URLs that feed that leaf.
#
# Hotpoint's per-page JSON-LD ItemList caps at ~50 products (their infinite-
# scroll tail loads via JS which we don't run). For any leaf whose total
# productCount exceeds ~50, we iterate its sub-categories to reach more of
# the catalog. Duplicates across parent + child URLs are deduped at the
# fetch site by product URL.
LEAF_TO_URLS: dict[str, list[str]] = {
    "tvs": [
        "https://hotpoint.co.ke/catalogue/category/tvs/",
        "https://hotpoint.co.ke/catalogue/category/tvs/tvs-by-feature/",
    ],
    "refrigerators": [
        "https://hotpoint.co.ke/catalogue/category/fridges-freezers/",
        "https://hotpoint.co.ke/catalogue/category/fridges-freezers/fridges/",
    ],
    "washers-dryers": [
        "https://hotpoint.co.ke/catalogue/category/washers-dryers/",
        "https://hotpoint.co.ke/catalogue/category/washers-dryers/washing-machines/",
        "https://hotpoint.co.ke/catalogue/category/washers-dryers/dryers/",
        "https://hotpoint.co.ke/catalogue/category/washers-dryers/twin-tubs/",
    ],
    "cooking": [
        "https://hotpoint.co.ke/catalogue/category/cookers-ovens/",
        "https://hotpoint.co.ke/catalogue/category/cookers-ovens/free-standing-cookers/",
        "https://hotpoint.co.ke/catalogue/category/cookers-ovens/microwave-ovens/",
        "https://hotpoint.co.ke/catalogue/category/cookers-ovens/table-top-cookers/",
        "https://hotpoint.co.ke/catalogue/category/cookers-ovens/toaster-ovens/",
    ],
    "audio": [
        "https://hotpoint.co.ke/catalogue/category/audio/",
        "https://hotpoint.co.ke/catalogue/category/audio/audio-type/",
    ],
    "blenders": [
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/kitchen-essentials/blenders/",
    ],
    "toasters": [
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/kitchen-essentials/toasters/",
    ],
    "kettles": [
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/kitchen-essentials/kettles/",
    ],
    "ironing-laundry": [
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/garment-care/",
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/garment-care/steam-irons/",
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/garment-care/dry-irons/",
        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/garment-care/garment-steamers/",
    ],
    # Note: Hotpoint's /solar/ / /solar-inverters/ / /solar-panels/ / /batteries/
    # URLs return 200 (Next.js catch-all) but the categories are empty as of
    # 2026-07-07 — the site nav no longer surfaces solar. Re-enable if that
    # changes. Left the fetch functions in place so it's a one-line flip.
}

# ListItem entries in the Next.js flight payload are doubly-escaped —
# outer JSON-in-JS-string. \\" is a backslash + quote inside a JS string.
# Names contain escaped inches marks and backslashes so we allow \\ sequences
# in the value character class.
_LISTITEM_RE = re.compile(
    r'\\"@type\\":\\"ListItem\\",\\"position\\":\d+,'
    r'\\"name\\":\\"((?:[^"\\]|\\\\.)+?)\\",'
    r'\\"url\\":\\"((?:[^"\\]|\\\\.)+?)\\"'
)

# Detail-page JSON-LD is regular (unescaped) JSON. The Product schema wraps
# a nested "offers" object which contains its own braces, so we allow any
# character (including braces) in the gap between "Product" and "price".
_PRODUCT_PRICE_RE = re.compile(
    r'"@type"\s*:\s*"Product".{0,5000}?"price"\s*:\s*"?([\d.]+)"?',
    re.DOTALL,
)
_PRODUCT_IMAGE_RE = re.compile(
    r'"@type"\s*:\s*"Product".{0,5000}?"image"\s*:\s*\[?\s*"([^"]+)"',
    re.DOTALL,
)


def _unescape_flight_str(s: str) -> str:
    """Reverse the Next.js flight JSON-in-JS-string escapes."""
    return s.replace("\\\\", "\\").replace("\\\"", '"').replace("\\/", "/")


async def _fetch_leaf(
    client: PoliteClient, url: str, category_slug: str
) -> AsyncIterator[RawListing]:
    resp = await client.get(url)
    items = _LISTITEM_RE.findall(resp.text)
    if not items:
        return
    for raw_name, raw_url in items:
        name = _unescape_flight_str(raw_name).strip()
        product_url = _unescape_flight_str(raw_url).strip()
        if not product_url.startswith("http"):
            product_url = "https://hotpoint.co.ke" + product_url

        # Fetch detail page for price.
        try:
            detail = await client.get(product_url)
        except Exception:  # noqa: BLE001
            continue
        price_m = _PRODUCT_PRICE_RE.search(detail.text)
        if not price_m:
            continue
        try:
            price = Decimal(price_m.group(1))
        except Exception:  # noqa: BLE001
            continue
        # Ksh 0 means listed but no price set — Hotpoint uses this for
        # "call for price" or upcoming items. Skip.
        if price <= 0:
            continue

        image_m = _PRODUCT_IMAGE_RE.search(detail.text)
        image_url = image_m.group(1) if image_m else None

        yield RawListing(
            merchant_slug=MERCHANT_SLUG,
            merchant_sku=None,
            url=product_url,
            title=name,
            price_kes=price,
            in_stock=True,
            image_url=image_url,
            category_slug=category_slug,
        )


async def _fetch_one(category_slug: str) -> AsyncIterator[RawListing]:
    urls = LEAF_TO_URLS.get(category_slug, [])
    if not urls:
        return
    client = PoliteClient()
    try:
        seen_product_urls: set[str] = set()
        for url in urls:
            async for r in _fetch_leaf(client, url, category_slug):
                if r.url in seen_product_urls:
                    continue
                seen_product_urls.add(r.url)
                yield r
    finally:
        await client.aclose()


async def fetch_tvs() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("tvs"):
        yield r


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("refrigerators"):
        yield r


async def fetch_washers_dryers() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("washers-dryers"):
        yield r


async def fetch_cooking() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("cooking"):
        yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("audio"):
        yield r


async def fetch_blenders() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("blenders"):
        yield r


async def fetch_toasters() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("toasters"):
        yield r


async def fetch_kettles() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("kettles"):
        yield r


async def fetch_irons() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("ironing-laundry"):
        yield r


async def fetch_inverters() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("inverters"):
        yield r


async def fetch_solar_panels() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("solar-panels"):
        yield r


async def fetch_solar_batteries() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("solar-batteries"):
        yield r
