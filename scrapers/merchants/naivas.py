"""Naivas Online scraper (electronics categories only).

Naivas runs a Laravel + Livewire storefront (Bagisto/Webkul). Category pages
are server-rendered HTML — no JS needed to see products or prices — but the
site sits behind Cloudflare and fingerprints the TLS handshake, so we fetch
through CffiPoliteClient (curl_cffi with Chrome impersonation) rather than
plain httpx.

Structure of a category page:
- 15 products per page. Pagination via ``?page=N``. When N exceeds the last
  populated page the response still returns 200 but contains 0 product cards,
  which is our natural stop condition.
- Each product card is a Livewire component div carrying ``wire:snapshot``
  whose memo.name is ``store.component.product-card-component``. We use those
  markers to split the page HTML into per-card chunks.
- Per-card fields:
    - Title + product URL: ``<a href="..." title="...">``
    - Sale price: first ``text-naivas-green`` span containing "KES <number>"
    - Regular price (optional): ``line-through`` span containing "KES <number>"
    - Image: ``cloudfront.net/product/<id>/<hash>.<ext>``
- Product id (used as merchant_sku) lives in the CloudFront path
  (``/product/<id>/``); we grab it from the image URL rather than trying to
  parse the escaped ``wire:snapshot`` JSON.

Naivas doesn't sell phones/tablets/laptops/gaming/cameras online, so LEAF_TO_URLS
is intentionally narrow to the appliance + TV + audio catalogue.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

MERCHANT_META = {
    "slug": "naivas-ke",
    "name": "Naivas Online",
    "base_url": "https://naivas.online",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

# PriceKenya leaf category slug → Naivas category page URLs.
# Multiple URLs per leaf are merged and deduped by product URL at fetch time.
LEAF_TO_URLS: dict[str, list[str]] = {
    "tvs": [
        "https://naivas.online/televisions/smart-tvs",
        "https://naivas.online/televisions/digital-tvs",
    ],
    "refrigerators": [
        "https://naivas.online/fridges-freezers/fridges",
    ],
    "freezers": [
        "https://naivas.online/fridges-freezers/freezers",
    ],
    "cooking": [
        "https://naivas.online/cookers/stand-alone-cookers",
        "https://naivas.online/cookers/table-top-burners",
        "https://naivas.online/cookers/electric-cookers-hot-plates",
        "https://naivas.online/kitchen-appliances/microwaves-ovens",
    ],
    "blenders": [
        "https://naivas.online/kitchen-appliances/blenders-juicers",
    ],
    "kettles": [
        "https://naivas.online/kitchen-appliances/electric-kettles-air-friers",
    ],
    "toasters": [
        "https://naivas.online/kitchen-appliances/sandwich-makers-toasters-coffee-makers",
    ],
    "ironing-laundry": [
        "https://naivas.online/garment-care/steam-iron-boxes",
        "https://naivas.online/garment-care/dry-iron-boxes",
    ],
    "audio": [
        "https://naivas.online/sound-system/sound-bars-bluetooth-speakers",
        "https://naivas.online/sound-system/hi-fi-home-theaters",
    ],
    "water-dispensers-coolers": [
        "https://naivas.online/kitchen-appliances/water-dispensers",
    ],
}

# Livewire card marker — divs whose wire:snapshot payload names the
# product-card-component. We split the page into chunks by these positions.
_CARD_MARKER_RE = re.compile(
    r'wire:snapshot="[^"]*product-card-component[^"]*"',
)
_TITLE_URL_RE = re.compile(
    r'href="(https://www\.naivas\.online/[^"?#]+)"[^>]*title="([^"]+)"'
)
_SALE_PRICE_RE = re.compile(
    r'text-naivas-green[^>]*>\s*KES[\s\xa0]([\d,\.]+)'
)
_IMAGE_RE = re.compile(
    r'<img[^>]+src="(https://[^"]+cloudfront\.net/product/(\d+)/[^"]+)"'
)

# Sanity cap on pagination — no Naivas category has this many pages, and a
# runaway page loop would hammer their servers.
_MAX_PAGES = 20


def _parse_price(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "").replace(" ", ""))
    except Exception:  # noqa: BLE001
        return None


def _parse_cards(page_html: str, category_slug: str) -> list[RawListing]:
    """Split the page into product cards and extract one RawListing per card."""
    marker_starts = [m.start() for m in _CARD_MARKER_RE.finditer(page_html)]
    if not marker_starts:
        return []
    listings: list[RawListing] = []
    for i, start in enumerate(marker_starts):
        end = marker_starts[i + 1] if i + 1 < len(marker_starts) else start + 8000
        card = page_html[start:end]

        title_m = _TITLE_URL_RE.search(card)
        sale_m = _SALE_PRICE_RE.search(card)
        if not title_m or not sale_m:
            continue

        product_url = title_m.group(1)
        title = html_lib.unescape(title_m.group(2)).strip()
        price = _parse_price(sale_m.group(1))
        if not price or price <= 0:
            continue

        image_url: str | None = None
        merchant_sku: str | None = None
        img_m = _IMAGE_RE.search(card)
        if img_m:
            image_url = img_m.group(1)
            merchant_sku = img_m.group(2)

        listings.append(
            RawListing(
                merchant_slug=MERCHANT_SLUG,
                merchant_sku=merchant_sku,
                url=product_url,
                title=title,
                price_kes=price,
                in_stock=True,
                image_url=image_url,
                category_slug=category_slug,
            )
        )
    return listings


async def _fetch_category(
    client: CffiPoliteClient, base_url: str, category_slug: str
) -> AsyncIterator[RawListing]:
    for page in range(1, _MAX_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001
            return
        listings = _parse_cards(resp.text, category_slug)
        if not listings:
            return
        for r in listings:
            yield r


async def _fetch_one(category_slug: str) -> AsyncIterator[RawListing]:
    urls = LEAF_TO_URLS.get(category_slug, [])
    if not urls:
        return
    client = CffiPoliteClient()
    try:
        seen: set[str] = set()
        for base_url in urls:
            async for r in _fetch_category(client, base_url, category_slug):
                if r.url in seen:
                    continue
                seen.add(r.url)
                yield r
    finally:
        await client.aclose()


async def fetch_tvs() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("tvs"):
        yield r


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("refrigerators"):
        yield r


async def fetch_freezers() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("freezers"):
        yield r


async def fetch_cooking() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("cooking"):
        yield r


async def fetch_blenders() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("blenders"):
        yield r


async def fetch_kettles() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("kettles"):
        yield r


async def fetch_toasters() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("toasters"):
        yield r


async def fetch_irons() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("ironing-laundry"):
        yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("audio"):
        yield r


async def fetch_water_dispensers() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("water-dispensers-coolers"):
        yield r
