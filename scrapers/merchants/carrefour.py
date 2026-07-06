"""Carrefour Kenya (carrefour.ke) scraper.

Carrefour's Kenya storefront runs a MAF-hosted Next.js SPA on top of an
Akamai wall. Plain httpx gets 200 with a shell only; `curl_cffi` with
Chrome TLS impersonation returns the full server-side-rendered HTML
including the React Server Components (RSC) hydration payload.

**Data source:** we ignore the visual HTML and parse the escaped-JSON
RSC payload instead — same data, cleaner extraction. Every product card
appears in the payload as a `productId/productName/sellingPrice/productUrl`
record with prices as integers (no comma parsing needed).

Sample record shape (after unescaping):
    "productId": "244834"
    "productName": "Lg Tv 65 4k Smart LED 65UA80006LC"
    "sellingPrice": 78995
    "markedPrice": 124995
    "productUrl": "/mafken/en/uhd-tv/lg-tv-65-4k-smart-led-65ua80006lc/p/244834"
    "defaultImages": ["https://cdn.mafrservices.com/.../244834_main.jpg?im=Resize=1700", ...]

**Category tree URL:** `/mafken/en/c/NFKEN4000000` is the Electronics &
Appliances parent (688 products across 12 pages at time of writing).
Pagination via `?currentPage=N` (0-indexed): page 0 is the bare URL,
pages 1..11 use the query param. Empty page = stop.

Smartphones/tablets/wearables live under a *separate* top-level category
tree (not NFKEN4000000). That's not covered by v0 — needs its own tree
ID discovered. For now Carrefour contributes fridges/TVs/cooking/audio
/blenders/kettles/toasters/ironing.

**Category routing:** Carrefour's URL slugs (`uhd-tv`, `washing-machine`,
`fridge-101l-to-200l`, `blender`, `kettle-glass`, etc.) are extracted
from the productUrl path segment `/mafken/en/<slug>/...` and mapped to
PriceKenya leaves. Batteries, adaptors, plugs, and heaters are skipped
(not covered by PriceKenya taxonomy).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

MERCHANT_META = {
    "slug": "carrefour-ke",
    "name": "Carrefour Kenya",
    "base_url": "https://www.carrefour.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

_BASE = "https://www.carrefour.ke"
_ELECTRONICS_URL = f"{_BASE}/mafken/en/c/NFKEN4000000"
_MAX_PAGES = 25  # Safety cap; totalPages is 12 today, room for growth.

# Carrefour subcategory URL slug → PriceKenya leaf slug.
# Slugs harvested from productUrl path segment `/mafken/en/<slug>/...`.
_SLUG_TO_LEAF: dict[str, str] = {
    # TVs
    "uhd-tv": "tvs",
    "qled-qned-tv": "tvs",
    "led-tv-26-43-": "tvs",
    "led-tv-44-55-": "tvs",
    "led-tv-above-55-": "tvs",
    # Fridges (any -l bucket)
    "fridge-101l-to-200l": "refrigerators",
    "fridge-201l-to-250l": "refrigerators",
    "fridge-251l-to-300l": "refrigerators",
    "fridge-301l-to-400l": "refrigerators",
    "fridge-above-400l": "refrigerators",
    "fridge-below-100l": "refrigerators",
    "chest-freezers": "freezers",
    "upright-freezers": "freezers",
    # Washing
    "washing-machine": "washers-dryers",
    "washer-dryer": "washers-dryers",
    "dryers": "washers-dryers",
    # Cooking
    "gas-electric-cookers": "cooking",
    "gas-cookers": "cooking",
    "electric-cookers": "cooking",
    # Small appliances
    "blender": "blenders",
    "hand-mixer": "blenders",
    "stand-mixer": "blenders",
    "food-processor": "blenders",
    "juicer": "blenders",
    "kettle-glass": "kettles",
    "kettle-plastic": "kettles",
    "kettle-stainless": "kettles",
    "kettle-stainless-steel": "kettles",
    "toaster": "toasters",
    "sandwich-maker": "toasters",
    "dry-irons": "ironing-laundry",
    "steam-irons": "ironing-laundry",
    "garment-steamers": "ironing-laundry",
    # Audio
    "home-cinema": "audio",
    "soundbars": "audio",
    "speakers": "audio",
    "bluetooth-speakers": "audio",
    "headphones": "audio",
    "earphones": "audio",
    # Water
    "water-dispensers": "water-dispensers-coolers",
    "water-coolers": "water-dispensers-coolers",
}

_SLUG_RE = re.compile(r"/mafken/en/([^/]+)/[^/]+/p/\d+")

# RSC payload regex. Products are pushed as escaped-JSON inside
# self.__next_f.push([1, "…"]) blocks, so quotes come through as \".
# Match the block from productId to sellingPrice; imageUrl comes right
# before productId so we grab it in the same look-back.
_PRODUCT_RE = re.compile(
    r'\\"productCompositeId\\":\\"[^\\]+\\",'
    r'\\"imageUrl\\":\\"([^\\]+)\\",'
    r'.*?'
    r'\\"productId\\":\\"(\d+)\\",'
    r'\\"productName\\":\\"([^\\]+)\\"'
    r'.*?'
    r'\\"sellingPrice\\":(\d+)'
    r'.*?'
    r'\\"productUrl\\":\\"([^\\]+)\\"',
    re.DOTALL,
)


def _unescape(name: str) -> str:
    """Decode \\u0026 → & and stray escapes inside the JS-string payload."""
    try:
        return name.encode("utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return name


def _route(product_url: str) -> str | None:
    m = _SLUG_RE.search(product_url)
    if not m:
        return None
    return _SLUG_TO_LEAF.get(m.group(1))


def _parse_page(text: str) -> list[RawListing]:
    seen_ids: set[str] = set()
    listings: list[RawListing] = []
    for m in _PRODUCT_RE.finditer(text):
        image_url, product_id, product_name, selling_price, product_url = m.groups()
        if product_id in seen_ids:
            continue
        seen_ids.add(product_id)

        leaf = _route(product_url)
        if not leaf:
            continue

        try:
            price = Decimal(selling_price)
        except Exception:  # noqa: BLE001
            continue
        if price <= 0:
            continue

        listings.append(
            RawListing(
                merchant_slug=MERCHANT_SLUG,
                merchant_sku=product_id,
                url=_BASE + product_url if product_url.startswith("/") else product_url,
                title=_unescape(product_name).strip(),
                price_kes=price,
                in_stock=True,
                image_url=image_url or None,
                category_slug=leaf,
            )
        )
    return listings


async def _fetch(client: CffiPoliteClient) -> AsyncIterator[RawListing]:
    seen: set[str] = set()
    for page in range(_MAX_PAGES):
        url = _ELECTRONICS_URL if page == 0 else f"{_ELECTRONICS_URL}?currentPage={page}"
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001
            return
        listings = _parse_page(resp.text)
        if not listings:
            return
        new_this_page = 0
        for r in listings:
            if r.url in seen:
                continue
            seen.add(r.url)
            new_this_page += 1
            yield r
        if new_this_page == 0:
            return


async def fetch_electronics() -> AsyncIterator[RawListing]:
    client = CffiPoliteClient()
    try:
        async for r in _fetch(client):
            yield r
    finally:
        await client.aclose()
