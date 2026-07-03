"""Ramtons Kenya (ramtons.com) scraper — Magento.

Standard Magento category pages with .product cards. Prices live in a
data-price-amount attribute (clean numeric string), titles in a nested
a.product-item-link, images in the srcset attribute.

Card duplication caveat: Magento's default layout renders each product
inside multiple ancestor containers, so `.product` counts include shadow
copies. We deduplicate by product URL.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "ramtons-ke",
    "name": "Ramtons Kenya",
    "base_url": "https://www.ramtons.com",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
BASE = MERCHANT_META["base_url"]

LEAF_TO_URL: dict[str, str] = {
    "refrigerators":   f"{BASE}/fridges-freezers/fridges",
    "washers-dryers":  f"{BASE}/washing-drying",
    "cooking":         f"{BASE}/cookers",
    "blenders":        f"{BASE}/small-kitchen-appliances/blenders",
    "toasters":        f"{BASE}/small-kitchen-appliances/toasters",
    "kettles":         f"{BASE}/small-kitchen-appliances/kettles",
    "ironing-laundry": f"{BASE}/small-home-appliances/garment-care",
}

_PRICE_ATTR_RE = re.compile(r'^\d+(?:\.\d+)?$')


def _extract(card, category_slug: str) -> tuple[str, RawListing] | None:
    link = card.css_first("a.product-item-link") or card.css_first(".product-item-name a")
    if not link:
        return None
    title = link.text(strip=True)
    href = link.attributes.get("href", "")
    if not (title and href):
        return None

    # Ramtons is a brand-direct site — every listing is a Ramtons SKU, but
    # their titles ("GAS COOKER 2 BURNER STAINLESS STEEL- RG/538") omit the
    # brand name. Inject it so the category matchers can find a brand token.
    if "ramtons" not in title.lower():
        title = f"Ramtons {title}"

    price_node = card.css_first("[data-price-amount]")
    if not price_node:
        return None
    amount = price_node.attributes.get("data-price-amount", "")
    if not _PRICE_ATTR_RE.match(amount):
        return None
    try:
        price = Decimal(amount)
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None

    image_url = None
    img = card.css_first("img")
    if img:
        srcset = img.attributes.get("srcset") or ""
        # srcset takes the first URL when it's a single-value string
        image_url = srcset.split(",")[0].strip().split()[0] if srcset else None
        if not image_url:
            image_url = img.attributes.get("data-src") or img.attributes.get("src")

    return href, RawListing(
        merchant_slug=MERCHANT_SLUG,
        merchant_sku=None,
        url=href,
        title=title,
        price_kes=price,
        in_stock=True,
        image_url=image_url,
        category_slug=category_slug,
    )


async def _fetch_leaf(leaf: str) -> AsyncIterator[RawListing]:
    url = LEAF_TO_URL.get(leaf)
    if not url:
        return
    client = PoliteClient()
    try:
        # Magento paginates with ?p=<n>; the first page is default.
        seen: set[str] = set()
        for page in range(1, 4):
            page_url = url if page == 1 else f"{url}?p={page}"
            try:
                resp = await client.get(page_url)
            except Exception:  # noqa: BLE001
                return
            html = HTMLParser(resp.text)
            new_this_page = 0
            for card in html.css(".product"):
                got = _extract(card, leaf)
                if not got:
                    continue
                href, listing = got
                if href in seen:
                    continue
                seen.add(href)
                new_this_page += 1
                yield listing
            # No new products on this page → we've hit the tail.
            if new_this_page == 0:
                return
    finally:
        await client.aclose()


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("refrigerators"):
        yield r


async def fetch_washers_dryers() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("washers-dryers"):
        yield r


async def fetch_cooking() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("cooking"):
        yield r


async def fetch_blenders() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("blenders"):
        yield r


async def fetch_toasters() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("toasters"):
        yield r


async def fetch_kettles() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("kettles"):
        yield r


async def fetch_irons() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("ironing-laundry"):
        yield r
