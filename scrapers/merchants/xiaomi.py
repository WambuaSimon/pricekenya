"""Xiaomi Kenya (xiaomistores.co.ke) scraper.

Xiaomi's Kenya presence is fragmented:
- `xiaomi-store.co.ke` (official) blocks curl_cffi at TLS — needs
  Playwright stealth. Not wired yet.
- `mi.com/ke/` is an SPA — no data in the initial HTML.
- `xiaomistores.co.ke` (this scraper) is a WooCommerce store with the
  full Kenya catalog. On 2026-07-16 they rebuilt the theme; the old
  HTML selectors we were parsing (woocommerce-LoopProduct-link,
  woocommerce-loop-product__title, product_cat-<slug> on <li>) all
  disappeared and the scraper started yielding zero rows silently
  (matrix leg reported success, DB went stale for ~75h).

**Approach: WooCommerce Store API.**

Store API `/wp-json/wc/store/v1/products` is enabled and public — no
authentication required. It exposes exactly the fields we need in
stable JSON, and it's an official WooCommerce endpoint that survives
theme rebuilds. Much lower failure surface than HTML scraping.

Pagination is controlled by `?per_page=100&page=N` and the
`X-WP-TotalPages` response header tells us when to stop.

Each product record includes:
  - name, permalink, slug
  - prices.price (integer string in minor units — 0 minor units for KES,
    so "74999" = KSh 74,999)
  - is_in_stock (bool)
  - categories[] with .slug — routed to PriceKenya leaves via
    _CATCLASS_TO_LEAF (same slug map that used to key off the old CSS
    classes, since WooCommerce category slugs are identical either way)
  - images[0].src for the primary image

Categories not in the map (wearables, household, iot-group, etc.) get
silently dropped — matches the old scraper's behavior.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

MERCHANT_META = {
    "slug": "xiaomi-ke",
    "name": "Xiaomi Kenya",
    "base_url": "https://xiaomistores.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

_STORE_API = "https://xiaomistores.co.ke/wp-json/wc/store/v1/products"
_PER_PAGE = 100
_MAX_PAGES = 20  # Safety cap; live count is 3 pages (271 products, Jul 2026).

# WooCommerce category slug → PriceKenya leaf. Order matters only for
# precedence when a product belongs to multiple categories — model-family
# specifics first (redmi-phones, poco-phones), generic catch-alls last
# (smartphones). Any slug not in this dict is ignored — that's how we
# skip iot-group / mombasa-shop / new-year / household / wearables.
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


def _route(categories: list[dict]) -> str | None:
    """Pick a PriceKenya leaf slug for this product's WooCommerce categories.

    Iterates the _CATCLASS_TO_LEAF dict in insertion order so specific
    model-family slugs beat the generic ones (redmi-phones before
    smartphones). Returns None when nothing matches — the ingest pipeline
    silently drops those.
    """
    slugs = {c.get("slug") for c in categories if c.get("slug")}
    for cls, leaf in _CATCLASS_TO_LEAF.items():
        if cls in slugs:
            return leaf
    return None


def _parse_product(p: dict) -> RawListing | None:
    """Convert one Store API product record to a RawListing, or None."""
    leaf = _route(p.get("categories") or [])
    if not leaf:
        return None

    prices = p.get("prices") or {}
    # KES has 0 minor units so the "price" string is already the whole KSh
    # amount. Some free/placeholder rows have empty or zero price — skip
    # them, they'd fail matcher rejection anyway.
    price_raw = prices.get("price") or ""
    try:
        price = Decimal(price_raw)
    except Exception:  # noqa: BLE001
        return None
    if price <= 0:
        return None

    title = (p.get("name") or "").strip()
    if not title:
        return None

    url = (p.get("permalink") or "").strip()
    if not url:
        return None

    images = p.get("images") or []
    img_url = images[0].get("src") if images else None

    return RawListing(
        merchant_slug=MERCHANT_SLUG,
        # WooCommerce's numeric product id is the stable SKU across a
        # slug rename. Fall back to slug when id is missing (shouldn't
        # happen against a real WC install but stay defensive).
        merchant_sku=str(p.get("id") or p.get("slug") or ""),
        url=url,
        title=title,
        price_kes=price,
        in_stock=bool(p.get("is_in_stock")),
        image_url=img_url,
        category_slug=leaf,
    )


async def _fetch(client: CffiPoliteClient) -> AsyncIterator[RawListing]:
    seen: set[int | str] = set()
    for page in range(1, _MAX_PAGES + 1):
        url = f"{_STORE_API}?per_page={_PER_PAGE}&page={page}"
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001 — network flake, stop cleanly
            return
        if resp.status_code >= 400:
            return
        try:
            products = json.loads(resp.text)
        except Exception:  # noqa: BLE001 — non-JSON response (WAF, etc.)
            return
        if not isinstance(products, list) or not products:
            return

        # X-WP-TotalPages tells us the last page. Stop when we've served
        # it so we don't hit an empty response on page +1.
        try:
            total_pages = int(resp.headers.get("X-WP-TotalPages") or 0)
        except Exception:  # noqa: BLE001
            total_pages = 0

        for raw in products:
            pid = raw.get("id") or raw.get("slug")
            if pid in seen:
                continue
            if pid is not None:
                seen.add(pid)
            listing = _parse_product(raw)
            if listing:
                yield listing

        if total_pages and page >= total_pages:
            return


async def fetch_all() -> AsyncIterator[RawListing]:
    client = CffiPoliteClient()
    try:
        async for r in _fetch(client):
            yield r
    finally:
        await client.aclose()
