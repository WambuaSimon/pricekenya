"""QuickMart Kenya scraper (electronics category only).

QuickMart runs a Growcer/Yo!Grocery PHP storefront gated by a "delivery
location + branch" session. The homepage and category URLs both return a
50 KB shell until the session carries all five location cookies. Landing
plain httpx (or curl_cffi without the session) gets nothing useful.

**Session bootstrap:** visiting the branch URL `/4301` (Quickmart Pioneer,
Nairobi CBD) sets `PHPSESSID` + the five `_ygGeo*` cookies + `_ygShopId=58`
in one hop — no POST or geolocation-form emulation required. All subsequent
category requests use that same `Session`.

**Category page:** `/electronics` (parent category id 61, shop id 58). One
category serves the whole electronics catalogue — no sub-URLs. 30 products
per page, `total_records` is embedded in the page (521 at time of writing).

**Pagination:** Growcer uses hyphen-separated key-value URL params, not
the `?key=value` you'd expect: `?page-2`, `?page-3`, etc. Standard
`?page=2` is silently ignored and re-serves page 1. Total records is
embedded in the first page (521 at time of writing → 18 pages, the last
partial with 11 items). Requesting a page past the last wraps back to
page 1 rather than 404ing, so we cap iteration by `ceil(total / 30)` and
use seen-URL dedup as a secondary safety net.

**Card structure:**
- Container: `<div class="products productInfoJs">`
- Title + URL: `<a class="products-title" title="..." href="...">` (attributes
  span multiple lines — use `re.DOTALL`)
- Sale price: `<span class="products-price-new">KES 34,995.00</span>`
- Regular price (optional): `<del class="products-price-old">KES 59,995.00</del>`
- SKU: `<input name="selprod_id" value="...">`
- Subcategory hint: `<input name="prodcat_id" value="...">`

**Category routing:** QuickMart's own `prodcat_id` gives the coarse split
(TVs, fridges, phones, audio, cooking, washers). For `prodcat_id=6152`
(the mixed small-appliance bucket) and unknown categories we fall back to
title-keyword rules, and skip anything we can't route to a PriceKenya leaf
(voltage protectors, fan heaters, sandwich makers — the matcher wouldn't
parse them anyway).
"""

from __future__ import annotations

import html as html_lib
import math
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

MERCHANT_META = {
    "slug": "quickmart-ke",
    "name": "Quickmart Kenya",
    "base_url": "https://www.quickmart.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

_BASE = "https://www.quickmart.co.ke"
_SESSION_BOOTSTRAP_URL = f"{_BASE}/4301"  # Quickmart Pioneer branch (Nairobi CBD)
_ELECTRONICS_URL = f"{_BASE}/electronics"
_PAGE_SIZE = 30

# QuickMart subcategory id → PriceKenya leaf slug. Values inferred from
# observing which prodcat_id the sample cards carried.
_PRODCAT_TO_LEAF: dict[str, str] = {
    "10": "tvs",
    "6150": "phones",
    "6151": "audio",
    "6153": "refrigerators",
    "6160": "washers-dryers",
    "6161": "cooking",
}

# Title keyword → PriceKenya leaf slug for the `prodcat_id=6152` bucket
# (kettles/toasters/irons/blenders all live there) and any unmapped cats.
# Ordered — first match wins.
_TITLE_KEYWORD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bkettle\b", re.I), "kettles"),
    (re.compile(r"\b(?:steam\s+iron|dry\s+iron|iron\s+box|ironing)\b", re.I), "ironing-laundry"),
    (re.compile(r"\b(?:toaster|sandwich\s+maker|bread\s+maker)\b", re.I), "toasters"),
    (re.compile(r"\b(?:blender|juicer|food\s+processor|mixer\s+grinder)\b", re.I), "blenders"),
    (re.compile(r"\bwater\s+dispenser\b", re.I), "water-dispensers-coolers"),
    (re.compile(r"\b(?:microwave|oven|cooker)\b", re.I), "cooking"),
    (re.compile(r"\b(?:speaker|soundbar|subwoofer|home\s+theat(?:re|er)|earbud|headphone)\b", re.I), "audio"),
    (re.compile(r"\b(?:washing\s+machine|dryer)\b", re.I), "washers-dryers"),
    (re.compile(r"\bfridge\b", re.I), "refrigerators"),
    (re.compile(r"\bfreezer\b", re.I), "freezers"),
    (re.compile(r"\btv\b", re.I), "tvs"),
]

_CARD_MARKER = '<div class="products productInfoJs">'
_TITLE_URL_RE = re.compile(
    r'<a\s+class="products-title"\s+title="([^"]+)"\s+href="(/[^"?#]+)"',
    re.DOTALL,
)
_SALE_PRICE_RE = re.compile(
    r'products-price-new">\s*KES[\s\xa0]([\d,\.]+)'
)
_IMAGE_RE = re.compile(
    r'<img\s+src="([^"]+/product_images_\d+\.[a-zA-Z]+[^"]*)"'
)
_SKU_RE = re.compile(r'name="selprod_id"\s+value="(\d+)"')
_PRODCAT_RE = re.compile(r'name="prodcat_id"\s+value="(\d+)"')
_TOTAL_RECORDS_RE = re.compile(r'id="total_records">(\d+)')


def _parse_price(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None


def _route_category(title: str, prodcat_id: str | None) -> str | None:
    """Pick a PriceKenya leaf slug for one card, or return None to skip it."""
    # Coarse prodcat_id map handles most cards cleanly.
    if prodcat_id and prodcat_id in _PRODCAT_TO_LEAF:
        return _PRODCAT_TO_LEAF[prodcat_id]
    # Fallback: title keyword rules (covers the mixed 6152 bucket and any
    # prodcat_ids QuickMart adds we haven't mapped yet).
    for pattern, slug in _TITLE_KEYWORD_RULES:
        if pattern.search(title):
            return slug
    return None


def _parse_cards(page_html: str) -> list[RawListing]:
    marker_positions = [i for i in _iter_marker_positions(page_html)]
    if not marker_positions:
        return []
    listings: list[RawListing] = []
    for i, start in enumerate(marker_positions):
        end = marker_positions[i + 1] if i + 1 < len(marker_positions) else start + 8000
        card = page_html[start:end]

        title_m = _TITLE_URL_RE.search(card)
        price_m = _SALE_PRICE_RE.search(card)
        if not title_m or not price_m:
            continue
        title = html_lib.unescape(title_m.group(1)).strip()
        product_path = title_m.group(2).strip()
        product_url = _BASE + product_path if product_path.startswith("/") else product_path
        price = _parse_price(price_m.group(1))
        if not price or price <= 0:
            continue

        prodcat_m = _PRODCAT_RE.search(card)
        prodcat_id = prodcat_m.group(1) if prodcat_m else None
        category_slug = _route_category(title, prodcat_id)
        if not category_slug:
            # Voltage protectors, sandwich makers, fan heaters — nothing
            # PriceKenya would meaningfully match against.
            continue

        img_m = _IMAGE_RE.search(card)
        sku_m = _SKU_RE.search(card)

        listings.append(
            RawListing(
                merchant_slug=MERCHANT_SLUG,
                merchant_sku=sku_m.group(1) if sku_m else None,
                url=product_url,
                title=title,
                price_kes=price,
                in_stock=True,
                image_url=img_m.group(1) if img_m else None,
                category_slug=category_slug,
            )
        )
    return listings


def _iter_marker_positions(page_html: str):
    start = 0
    while True:
        idx = page_html.find(_CARD_MARKER, start)
        if idx == -1:
            return
        yield idx
        start = idx + len(_CARD_MARKER)


async def _fetch_electronics(client: CffiPoliteClient) -> AsyncIterator[RawListing]:
    # Bootstrap the session — one GET sets all five location cookies + shop.
    await client.get(_SESSION_BOOTSTRAP_URL)

    # Fetch page 1 to learn total_records, then iterate the rest.
    first = await client.get(_ELECTRONICS_URL)
    total_m = _TOTAL_RECORDS_RE.search(first.text)
    total_records = int(total_m.group(1)) if total_m else 0
    if total_records <= 0:
        return
    total_pages = math.ceil(total_records / _PAGE_SIZE)

    seen: set[str] = set()
    for page in range(1, total_pages + 1):
        if page == 1:
            page_html = first.text
        else:
            resp = await client.get(f"{_ELECTRONICS_URL}?page-{page}")
            page_html = resp.text
        listings = _parse_cards(page_html)
        new_this_page = 0
        for r in listings:
            if r.url in seen:
                continue
            seen.add(r.url)
            new_this_page += 1
            yield r
        # Safety: if a page adds nothing new, we've hit QuickMart's page-1
        # wraparound and further pages are duplicates.
        if new_this_page == 0 and page > 1:
            return


async def fetch_electronics() -> AsyncIterator[RawListing]:
    client = CffiPoliteClient()
    try:
        async for r in _fetch_electronics(client):
            yield r
    finally:
        await client.aclose()
