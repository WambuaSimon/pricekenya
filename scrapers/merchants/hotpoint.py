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

# Our leaf category slug → Hotpoint's category URL.
LEAF_TO_URL: dict[str, str] = {
    "tvs":             "https://hotpoint.co.ke/catalogue/category/tvs/",
    "refrigerators":   "https://hotpoint.co.ke/catalogue/category/fridges-freezers/",
    "washers-dryers":  "https://hotpoint.co.ke/catalogue/category/washers-dryers/",
    "cooking":         "https://hotpoint.co.ke/catalogue/category/cookers-ovens/",
    "audio":           "https://hotpoint.co.ke/catalogue/category/audio/",
    "blenders":        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/kitchen-essentials/blenders/",
    "toasters":        "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/kitchen-essentials/toasters/",
    "kettles":         "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/kitchen-essentials/kettles/",
    "ironing-laundry": "https://hotpoint.co.ke/catalogue/category/kitchen-small-home-appliances/garment-care/",
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
    url = LEAF_TO_URL.get(category_slug)
    if not url:
        return
    client = PoliteClient()
    try:
        async for r in _fetch_leaf(client, url, category_slug):
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
