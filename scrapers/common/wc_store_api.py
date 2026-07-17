"""Shared WooCommerce Store API scraper.

Any WC store that leaves `/wp-json/wc/store/v1/products` open (the default
for a stock WooCommerce install) can be scraped through this helper. It
is vastly more reliable than parsing HTML — the Store API is an official
WC endpoint that survives theme rebuilds. It also delivers structured
JSON with prices, stock, categories, and images in one shot, so we don't
have to babysit fragile selectors per merchant.

The xiaomi-ke merchant proved this approach after their theme rebuild on
2026-07-16 broke the HTML scraper (silent zero yield for 75 hours). The
helper below extracts that same pattern so any WC merchant can adopt it
in a few lines.

Category routing:
  Every product returned by the API carries a `categories[]` array with
  slugs like "smartphones", "wireless-earbuds", "hobs" etc. We iterate
  each product's categories against UNIVERSAL_CATEGORY_MAP (merged with
  any merchant-specific overrides) and take the first hit as the
  PriceKenya leaf. Products whose categories aren't in the map get
  silently dropped — that's how we skip generic marketing buckets like
  "best-sellers", "hot-deals", "bundle-offers".
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

# WooCommerce category slug → PriceKenya leaf. Insertion order matters
# ONLY when two entries would route the same product to different leaves
# via different category tags — Python dicts preserve insertion order so
# more-specific slugs (`hp-laptops`) sit before generic brand-only ones
# (`hp`). In practice most products have a specific category first, so
# the dominant loop is "iterate the product's categories, first hit
# in the map wins."
UNIVERSAL_CATEGORY_MAP: dict[str, str] = {
    # ---- Phones ----
    "5g-phones": "phones",
    "5g-phones-in-kenya": "phones",
    "budget-smartphones": "phones",
    "curved-display-phones": "phones",
    "hmd-phones": "phones",
    "itel-phones": "phones",
    "zte-phones": "phones",
    "honor-phones": "phones",
    "vivo-phones": "phones",
    "realme-phones": "phones",
    "oppo-phones": "phones",
    "infinix-phones": "phones",
    "tecno-phones": "phones",
    "xiaomi-phones": "phones",
    "redmi-phones": "phones",
    "poco-phones": "phones",
    "iphone": "phones",
    "iphones": "phones",
    "apple-iphones": "phones",
    "apple-iphones-in-kenya": "phones",
    "smartphones": "phones",
    "mobile-phones": "phones",
    "phones": "phones",
    # ---- Tablets ----
    "kids-tablets-in-kenya": "tablets",
    "kids-tablets": "tablets",
    "ipad": "tablets",
    "ipads": "tablets",
    "tablets": "tablets",
    "tablet": "tablets",
    # ---- Laptops ----
    "gaming-laptops": "laptops",
    "business-laptops": "laptops",
    "premium-laptops": "laptops",
    "creator-laptops": "laptops",
    "apple-macbooks": "laptops",
    "lenovo-laptops": "laptops",
    "hp-laptops": "laptops",
    "dell-laptops": "laptops",
    "asus-laptops": "laptops",
    "macbook": "laptops",
    "notebook": "laptops",
    "laptop": "laptops",
    "laptops": "laptops",
    "computers-tablets": "laptops",
    # ---- TVs ----
    "smart-tvs": "tvs",
    "smart-tv": "tvs",
    "led-tv": "tvs",
    "frame-less-tv": "tvs",
    "hisense-tv": "tvs",
    "hisense-smart-tv": "tvs",
    "samsung-tv": "tvs",
    "lg-tv": "tvs",
    "televisions": "tvs",
    "tvs": "tvs",
    "tv": "tvs",
    # ---- Audio ----
    "wireless-earbuds": "audio",
    "noise-cancelling-earbuds": "audio",
    "hifi-and-woofers": "audio",
    "home-theater": "audio",
    "theater": "audio",
    "shop-by-brand-theater": "audio",
    "lg-shop-by-brand-theater": "audio",
    "earbuds": "audio",
    "headphones": "audio",
    "jbl-headphones": "audio",
    "jbl": "audio",  # JBL is exclusively audio in this catalog context
    "speakers": "audio",
    "soundbars": "audio",
    "audio": "audio",
    # ---- Cameras ----
    "cctv-cameras": "cameras",
    "cctv": "cameras",
    "digital-cameras": "cameras",
    "action-cameras": "cameras",
    "cameras": "cameras",
    # ---- Refrigerators (includes freezers until we split that leaf) ----
    "hisense-fridges-in-kenya": "refrigerators",
    "hisense-fridges": "refrigerators",
    "double-door": "refrigerators",
    "built-in-fridges-and-freezers": "refrigerators",
    "chest-freezers": "refrigerators",
    "fridges": "refrigerators",
    "refrigerators": "refrigerators",
    # ---- Washers / dryers ----
    "hisense-washing-machine": "washers-dryers",
    "washing-machines": "washers-dryers",
    "washing-machine": "washers-dryers",
    # ---- Dishwashers (own leaf as of 2026-07-17) ----
    "built-in-dishwashers": "dishwashers",
    "dishwashers": "dishwashers",
    # ---- Cooking (hobs / cookers / ovens / microwaves) ----
    "gas-and-induction-hobs": "cooking",
    "gas-electric-hobs": "cooking",
    "induction-hobs": "cooking",
    "gas-hobs": "cooking",
    "hobs": "cooking",
    "built-in-electric-ovens": "cooking",
    "ovens-collection": "cooking",
    "ovens": "cooking",
    "microwaves": "cooking",
    "gas-cooker": "cooking",
    "gas-cookers": "cooking",
    "gaselectric": "cooking",
    # ---- Small kitchen appliances ----
    "kettles": "kettles",
    "toasters": "toasters",
    "blenders": "blenders",
    # ---- Coffee machines (own leaf as of 2026-07-17) ----
    "coffee-machines": "coffee-machines",
    "coffee-machine": "coffee-machines",
    "coffee-makers": "coffee-machines",
    "coffee-maker": "coffee-machines",
    "espresso-machines": "coffee-machines",
    # ---- Home & kitchen fixtures (Newmatic's non-appliance catalog) ----
    "sinks-and-taps": "kitchen-sinks-taps",
    "sinks": "kitchen-sinks-taps",
    "taps": "kitchen-sinks-taps",
    "kitchen-sinks": "kitchen-sinks-taps",
    "countertops": "countertops",
    "counter-tops": "countertops",
    "splashbacks": "splashbacks",
    "kitchen-hardware": "kitchen-hardware",
    "utensils-kitchenware": "utensils",
    "utensils": "utensils",
    "kitchenware": "utensils",
    "toilets": "toilets",
    "wc-toilets": "toilets",
    # ---- Ironing / laundry small ----
    "irons": "ironing-laundry",
    "steam-irons": "ironing-laundry",
    # ---- Phone / tablet accessories ----
    "high-capacity-power-banks": "phone-tablet-accessories",
    "power-banks": "phone-tablet-accessories",
    "mobile-accessories": "phone-tablet-accessories",
    "phone-accessories": "phone-tablet-accessories",
    "chargers": "phone-tablet-accessories",
    "charging-cables": "phone-tablet-accessories",
    "power-extensions": "phone-tablet-accessories",
    "accessories": "phone-tablet-accessories",
    "accessories-2": "phone-tablet-accessories",
    # ---- Peripherals / computing accessories ----
    "tp-link-routers": "peripherals-accessories",
    "wi-fi-routers": "peripherals-accessories",
    "monitors": "peripherals-accessories",
    "displays": "peripherals-accessories",
    "printers": "peripherals-accessories",
    "multifunction-printers": "peripherals-accessories",
    "projectors": "peripherals-accessories",
    "networking": "peripherals-accessories",
    "interactive-displays": "peripherals-accessories",
    "smart-boards": "peripherals-accessories",
    # ---- Solar / inverters ----
    "solar-batteries": "solar-batteries",
    "solar-battery": "solar-batteries",
    "solar-panels": "solar-panels",
    "solar-panel": "solar-panels",
    "inverters": "inverters",
    "inverter": "inverters",
}


def _route(categories: list[dict], override_map: dict[str, str] | None = None) -> str | None:
    """Pick a PriceKenya leaf slug from a product's WC categories.

    Returns None when nothing matches — the caller silently drops those.
    override_map takes precedence over UNIVERSAL_CATEGORY_MAP for the same
    slug, so a merchant with a quirky slug ("theater" → tvs, not audio)
    can override just that one entry without duplicating the rest.
    """
    merged = {**UNIVERSAL_CATEGORY_MAP, **(override_map or {})}
    for c in categories:
        slug = c.get("slug")
        if slug and slug in merged:
            return merged[slug]
    return None


async def fetch_wc_store_catalog(
    base_url: str,
    merchant_slug: str,
    *,
    override_category_map: dict[str, str] | None = None,
    per_page: int = 100,
    max_pages: int = 40,
) -> AsyncIterator[RawListing]:
    """Iterate `/wp-json/wc/store/v1/products` and yield RawListings.

    Pagination stops when either (a) the response has fewer results than
    per_page, (b) X-WP-TotalPages says we've served the last page, or
    (c) max_pages is hit as a safety cap.
    """
    base = base_url.rstrip("/")
    api = f"{base}/wp-json/wc/store/v1/products"
    client = CffiPoliteClient()
    seen: set = set()
    try:
        for page in range(1, max_pages + 1):
            try:
                resp = await client.get(f"{api}?per_page={per_page}&page={page}")
            except Exception:  # noqa: BLE001 — network flake, stop the loop
                return
            if resp.status_code >= 400:
                return
            try:
                products = json.loads(resp.text)
            except Exception:  # noqa: BLE001 — WAF page, HTML error etc.
                return
            if not isinstance(products, list) or not products:
                return
            try:
                total_pages = int(resp.headers.get("X-WP-TotalPages") or 0)
            except Exception:  # noqa: BLE001
                total_pages = 0

            for p in products:
                pid = p.get("id") or p.get("slug")
                if pid in seen:
                    continue
                if pid is not None:
                    seen.add(pid)

                leaf = _route(p.get("categories") or [], override_category_map)
                if not leaf:
                    continue

                prices = p.get("prices") or {}
                # KES has 0 minor units — the "price" string is the whole
                # KSh amount. Some free / placeholder rows carry "0" or
                # empty; skip them so we don't dirty the DB.
                try:
                    price = Decimal(prices.get("price") or "0")
                except Exception:  # noqa: BLE001
                    continue
                if price <= 0:
                    continue

                title = (p.get("name") or "").strip()
                if not title:
                    continue
                url = (p.get("permalink") or "").strip()
                if not url:
                    continue

                images = p.get("images") or []
                yield RawListing(
                    merchant_slug=merchant_slug,
                    merchant_sku=str(p.get("id") or p.get("slug") or ""),
                    url=url,
                    title=title,
                    price_kes=price,
                    in_stock=bool(p.get("is_in_stock")),
                    image_url=images[0].get("src") if images else None,
                    category_slug=leaf,
                )

            if total_pages and page >= total_pages:
                return
    finally:
        await client.aclose()
