"""Phones Store Kenya (phonesstorekenya.com) scraper.

Same customised WooCommerce theme as Phone Place (STLA/8theme-style) but
sitting on plain httpx — no Cloudflare wall, so uses PoliteClient rather
than CffiPoliteClient.

Card structure mirrors phone_place.py exactly:
- `.products > .product-wrapper` for card containers, 24/page.
- Title in `img alt`, product URL in the `a[href*="/product/"]`.
- Price sits on the parent cell (`.product-wrapper` is a child), so we walk
  up one level to find `.price bdi`.
- Merchant SKU on any descendant carrying `data-product_id`.
- Pagination via WooCommerce standard `/page/N/`; empty page = stop.

Phones Store's taxonomy is Apple-heavy but does carry audio, gaming
(consoles + accessories), cameras (in "creator-equipment"), and ex-UK
phones. Tablet coverage comes from the `apple-ipad/` subcategory.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "phonesstore-ke",
    "name": "Phones Store Kenya",
    "base_url": "https://phonesstorekenya.com",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

LEAF_TO_URLS: dict[str, list[str]] = {
    "phones": [
        "https://phonesstorekenya.com/product-category/apple-iphone/",
        "https://phonesstorekenya.com/product-category/ex-uk-phones/",
    ],
    "tablets": [
        "https://phonesstorekenya.com/product-category/apple-iphone/apple-ipad/",
    ],
    "laptops": [
        "https://phonesstorekenya.com/product-category/apple-iphone/macbooks/",
    ],
    "audio": [
        "https://phonesstorekenya.com/product-category/audio/",
    ],
    "cameras": [
        "https://phonesstorekenya.com/product-category/creator-equipment/cameras/",
    ],
    "phone-tablet-accessories": [
        "https://phonesstorekenya.com/product-category/apple-iphone/apple-accessories/",
        "https://phonesstorekenya.com/product-category/apple-iphone/apple-pencil/",
    ],
    "console-accessories": [
        "https://phonesstorekenya.com/product-category/gaming/controller/",
        "https://phonesstorekenya.com/product-category/gaming/gaming-accessories/",
    ],
    # gaming-consoles is actual consoles, not accessories. Left here for a
    # future gaming-consoles leaf; today no matcher exists for the "gaming"
    # category so ingest silently drops.
    "gaming": [
        "https://phonesstorekenya.com/product-category/gaming/gaming-consoles/",
    ],
}

_PRICE_RE = re.compile(r"[\d,]+")
_MAX_PAGES = 20


def _parse_price(raw: str) -> Decimal | None:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _extract_from_card(card, container, category_slug: str) -> RawListing | None:
    a = card.css_first('a[href*="/product/"]')
    img = card.css_first("img")
    if not (a and img):
        return None
    product_url = a.attributes.get("href", "")
    if not product_url.startswith("http"):
        product_url = "https://phonesstorekenya.com" + product_url

    title = (img.attributes.get("alt") or "").strip()
    if not title:
        return None

    price_node = (
        container.css_first(".price ins bdi")
        or container.css_first(".price bdi")
        or container.css_first(".price .amount")
        or container.css_first(".price")
    )
    if not price_node:
        return None
    price = _parse_price(price_node.text(strip=True))
    if price is None or price <= 0:
        return None

    image_url = (
        img.attributes.get("data-src")
        or img.attributes.get("data-lazy-src")
        or img.attributes.get("src")
    )
    if image_url and (image_url.startswith("data:image") or "svg+xml" in image_url):
        srcset = img.attributes.get("data-srcset") or ""
        image_url = srcset.split()[0] if srcset else None

    sku = None
    sku_node = card.css_first("[data-product_id]")
    if sku_node:
        sku = sku_node.attributes.get("data-product_id")

    return RawListing(
        merchant_slug=MERCHANT_SLUG,
        merchant_sku=sku,
        url=product_url,
        title=title,
        price_kes=price,
        in_stock=True,
        image_url=image_url,
        category_slug=category_slug,
    )


async def _fetch_category(
    client: PoliteClient, base_url: str, category_slug: str
) -> AsyncIterator[RawListing]:
    for page in range(1, _MAX_PAGES + 1):
        url = base_url.rstrip("/") + "/"
        if page > 1:
            url = url + f"page/{page}/"
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001
            return
        tree = HTMLParser(resp.text)
        main = tree.css_first(".products")
        if not main:
            return
        cards = main.css(".product-wrapper")
        if not cards:
            return
        for card in cards:
            container = card.parent or card
            listing = _extract_from_card(card, container, category_slug)
            if listing:
                yield listing


async def _fetch_one(category_slug: str) -> AsyncIterator[RawListing]:
    urls = LEAF_TO_URLS.get(category_slug, [])
    if not urls:
        return
    client = PoliteClient()
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


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("phones"):
        yield r


async def fetch_tablets() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("tablets"):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("laptops"):
        yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("audio"):
        yield r


async def fetch_cameras() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("cameras"):
        yield r


async def fetch_accessories() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("phone-tablet-accessories"):
        yield r


async def fetch_console_accessories() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("console-accessories"):
        yield r


async def fetch_gaming() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("gaming"):
        yield r
