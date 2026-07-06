"""Xiaomi Kenya (xiaomistores.co.ke) scraper.

Xiaomi's Kenya presence is fragmented:
- `mi.com/ke/` is an official SPA — 200 OK with `curl_cffi` but zero
  product data in the HTML shell (client-side rendered).
- `xiaomi-store.co.ke` returns 403 even with Chrome TLS impersonation.
- Older recon dismissed `xiaomistores.co.ke` as "identical widget
  content" — but that was based on category-URL testing. The `/shop/`
  paginated listing IS the full catalogue: 266 products (Nov 2026)
  across 12 pages of 24 items each, all with real KSh pricing.

xiaomistores.co.ke is a customised WooCommerce (WordPress + WP Rocket
cache). No CF/Akamai wall — plain `CffiPoliteClient` works cleanly.

**Card structure:**
- Container: `<li class="product ... product_cat-<slug> ...">`
- URL: `<a href="…" class="woocommerce-LoopProduct-link woocommerce-loop-product__link">`
- Product URLs are FLAT (`https://xiaomistores.co.ke/redmi-15c-4gb-256gb/`),
  not `/product/<slug>/`.
- Title: `<div class="woocommerce-loop-product__title">…</div>` inside
  or after the anchor.
- Price: prefer the `<ins>` block (sale price) over `<del>` (marked
  price). Currency symbol is `KSh` inside a
  `.woocommerce-Price-currencySymbol` span; the number sits after
  `&nbsp;`.
- Image: `<img data-lazy-src="…">` since WP Rocket lazyloads.

**Category routing:** WooCommerce tags every card with all its taxonomy
ancestors as `product_cat-<slug>` classes on the `<li>`. We iterate
those in a specificity-ordered map and pick the first hit — this
naturally avoids the "iot-group" / "mi-shop" / "mombasa-shop" catch-all
categories that would misroute otherwise.

Wearables (`mi-watches-bands`, `amazfit`, `mibro`, `watches`,
`smartwatches`) and lifestyle SKUs (`household`, `personal-care`,
`purifier-vacuum`) are dropped: PriceKenya's taxonomy doesn't cover
them and the matcher would reject them anyway. WiFi extenders/routers
similarly skipped for now.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

MERCHANT_META = {
    "slug": "xiaomi-ke",
    "name": "Xiaomi Kenya",
    "base_url": "https://xiaomistores.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

_BASE = "https://xiaomistores.co.ke"
_SHOP_URL = f"{_BASE}/shop/"
_MAX_PAGES = 20  # Safety cap; live count is ~12 pages.

# Ordered — first match wins. Specificity: model-specific first, generic
# catch-alls last. Any class not in this dict is ignored (which is what
# skips iot-group, mombasa-shop, new-year, household, wearables, etc.).
_CATCLASS_TO_LEAF: dict[str, str] = {
    # Phones (Redmi/Poco/Mi model families first, then generic)
    "redmi-phones": "phones",
    "poco-phones": "phones",
    "mi-phones": "phones",
    "redmi-note-15-series": "phones",
    "smartphones": "phones",
    # Tablets
    "redmi-tablets": "tablets",
    "xiaomi-tablets": "tablets",
    # TVs
    "xiaomi-smart-tvs": "tvs",
    "xiaomi-tv-stick": "tvs",
    # Audio
    "earbuds": "audio",
    "xiaomi-speakers": "audio",
    "mi-earphones": "audio",
    "devices-audio": "audio",
    # Cameras
    "cameras": "cameras",
    "dashcam": "cameras",
    # Phone/tablet accessories
    "chargers": "phone-tablet-accessories",
    "charging-cables": "phone-tablet-accessories",
    "powerbanks": "phone-tablet-accessories",
    "powerbank-charging": "phone-tablet-accessories",
    "xiaomi-tablet-accessories": "phone-tablet-accessories",
    "covers-protectors": "phone-tablet-accessories",
}

_LI_RE = re.compile(r'<li class="product ([^"]+)">', re.DOTALL)
_URL_RE = re.compile(
    r'<a href="([^"]+)"[^>]*class="woocommerce-LoopProduct-link[^"]*"'
)
_TITLE_RE = re.compile(
    r'class="woocommerce-loop-product__title"[^>]*>([^<]+)<'
)
_INS_PRICE_RE = re.compile(
    r'<ins>.*?<span class="woocommerce-Price-currencySymbol"[^>]*>KSh</span>'
    r'[\s&nbsp;]*([\d,]+)',
    re.DOTALL,
)
_ANY_PRICE_RE = re.compile(
    r'<span class="woocommerce-Price-currencySymbol"[^>]*>KSh</span>'
    r'[\s&nbsp;]*([\d,]+)'
)
_IMG_RE = re.compile(r'data-lazy-src="([^"]+\.(?:webp|jpg|jpeg|png))"')
_SLUG_URL_RE = re.compile(r"https?://xiaomistores\.co\.ke/([^/]+)/?$")


def _parse_price(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None


def _route(classes: str) -> str | None:
    # Extract product_cat-<slug> tokens from the class string.
    cats = set(re.findall(r"product_cat-([a-z0-9\-]+)", classes))
    for cls, leaf in _CATCLASS_TO_LEAF.items():
        if cls in cats:
            return leaf
    return None


def _parse_cards(page_html: str) -> list[RawListing]:
    positions = [(m.start(), m.group(1)) for m in _LI_RE.finditer(page_html)]
    listings: list[RawListing] = []
    for i, (start, classes) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else start + 10000
        block = page_html[start:end]

        leaf = _route(classes)
        if not leaf:
            continue

        url_m = _URL_RE.search(block)
        title_m = _TITLE_RE.search(block)
        if not url_m or not title_m:
            continue
        product_url = html_lib.unescape(url_m.group(1)).strip()
        title = html_lib.unescape(title_m.group(1)).strip()

        # Sale price if present, else the first .woocommerce-Price-amount.
        price_m = _INS_PRICE_RE.search(block) or _ANY_PRICE_RE.search(block)
        if not price_m:
            continue
        price = _parse_price(price_m.group(1))
        if not price or price <= 0:
            continue

        img_m = _IMG_RE.search(block)

        # Merchant SKU: use the URL slug — Xiaomi Kenya's WooCommerce
        # doesn't expose numeric product_ids in the loop cards.
        slug_m = _SLUG_URL_RE.match(product_url)
        sku = slug_m.group(1) if slug_m else None

        listings.append(
            RawListing(
                merchant_slug=MERCHANT_SLUG,
                merchant_sku=sku,
                url=product_url,
                title=title,
                price_kes=price,
                in_stock=True,
                image_url=img_m.group(1) if img_m else None,
                category_slug=leaf,
            )
        )
    return listings


async def _fetch(client: CffiPoliteClient) -> AsyncIterator[RawListing]:
    seen: set[str] = set()
    for page in range(1, _MAX_PAGES + 1):
        url = _SHOP_URL if page == 1 else f"{_SHOP_URL}page/{page}/"
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001
            return
        if resp.status_code >= 400:
            return
        listings = _parse_cards(resp.text)
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


async def fetch_all() -> AsyncIterator[RawListing]:
    client = CffiPoliteClient()
    try:
        async for r in _fetch(client):
            yield r
    finally:
        await client.aclose()
