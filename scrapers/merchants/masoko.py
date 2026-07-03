"""Masoko (Safaricom's electronics shop, masoko.com) scraper.

Next.js frontend on Magento GraphQL backend. Category pages embed the full
product list in the `__NEXT_DATA__` JSON payload — clean and reliable to
parse. Each item carries: id, sku, name, price, specialPrice, thumbnail,
urlPath, stock.

Falls back to `specialPrice` when it's set and less than `price` (Masoko
uses it for sale pricing).
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "masoko",
    "name": "Masoko",
    "base_url": "https://www.masoko.com",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
BASE = MERCHANT_META["base_url"]

LEAF_TO_URL: dict[str, str] = {
    "phones":  f"{BASE}/phones-accessories/mobile-phones",
    "tablets": f"{BASE}/phones-accessories/tablets",
    "laptops": f"{BASE}/laptops",
    # Router coverage overlaps our computing subtree — not a leaf yet, skip
    # until we decide where routers live.
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.+?)</script>',
    re.DOTALL,
)


def _dig(obj, *keys):
    """Safe nested-dict getter."""
    for k in keys:
        if not isinstance(obj, dict) or k not in obj:
            return None
        obj = obj[k]
    return obj


def _pick_price(item: dict) -> Decimal | None:
    """Prefer specialPrice when it's a real discount, else regular price."""
    price = item.get("price")
    special = item.get("specialPrice")
    candidate: str | None = None
    if special:
        try:
            if price and Decimal(str(special)) < Decimal(str(price)):
                candidate = str(special)
            else:
                candidate = str(special)
        except Exception:  # noqa: BLE001
            candidate = str(price) if price else None
    else:
        candidate = str(price) if price else None
    if not candidate:
        return None
    try:
        p = Decimal(candidate)
    except Exception:  # noqa: BLE001
        return None
    return p if p > 0 else None


async def _fetch_leaf(leaf: str) -> AsyncIterator[RawListing]:
    url = LEAF_TO_URL.get(leaf)
    if not url:
        return
    client = PoliteClient()
    try:
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001
            return
        m = _NEXT_DATA_RE.search(resp.text)
        if not m:
            return
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return

        items = _dig(data, "props", "pageProps", "category", "categoryPage", "items")
        if not isinstance(items, list):
            return

        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            url_path = item.get("urlPath")
            if not (name and url_path):
                continue
            price = _pick_price(item)
            if price is None:
                continue
            product_url = f"{BASE}/{url_path.lstrip('/')}"
            image_url = item.get("thumbnail") or None
            yield RawListing(
                merchant_slug=MERCHANT_SLUG,
                merchant_sku=item.get("sku"),
                url=product_url,
                title=name,
                price_kes=price,
                in_stock=bool(_dig(item, "stock", "isInStock") if item.get("stock") else True),
                image_url=image_url,
                category_slug=leaf,
            )
    finally:
        await client.aclose()


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("phones"):
        yield r


async def fetch_tablets() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("tablets"):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _fetch_leaf("laptops"):
        yield r
