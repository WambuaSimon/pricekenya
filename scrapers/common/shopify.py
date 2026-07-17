"""Shared Shopify scraping helper.

Shopify exposes every store's catalogue at `/products.json` (paginated at
`?page=N`, capped at 250/page). Each product carries title, handle,
vendor, product_type, tags, images, and a `variants` list where variant[0]
holds the primary price. This is dramatically easier than HTML scraping —
no selectors to babysit, no lazy-loaded images.

Category routing:
  - Prefer `product_type` when the store fills it in (Zentech-style).
  - Fall back to keyword matching on the title when it's empty
    (Digitalcity-style — every product_type is "").

Products that don't map to any PriceKenya leaf are silently dropped; the
ingest pipeline never sees them. This matches how the HTML scrapers
already handle unrecognised categories.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import CffiPoliteClient, RawListing

# Cheap HTML-to-text: drop <script>/<style> blocks, then all remaining tags.
# `body_html` from /products.json can contain <p>, <ul>, <br>, escaped
# entities, and inline styling. The matcher only cares that numeric spec
# tokens like "128GB" survive intact — we don't need a full HTML parser.
_HTML_BLOCK_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = _HTML_BLOCK_RE.sub(" ", html)
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()

# Shopify `product_type` string → PriceKenya taxonomy leaf.
# Match longest key first (case-insensitive substring) so specific beats generic.
PRODUCT_TYPE_TO_LEAF: dict[str, str] = {
    "power bank": "phone-tablet-accessories",
    "wireless earbuds": "phone-tablet-accessories",
    "wireless earphones": "phone-tablet-accessories",
    "earbuds": "phone-tablet-accessories",
    "smartwatch": "phone-tablet-accessories",
    "smart watch": "phone-tablet-accessories",
    "charger": "phone-tablet-accessories",
    "cable": "phone-tablet-accessories",
    "usb hub": "peripherals-accessories",
    "keyboard": "peripherals-accessories",
    "mouse": "peripherals-accessories",
    "webcam": "peripherals-accessories",
    "headphones": "audio",
    "headphone": "audio",
    "speaker": "audio",
    "soundbar": "audio",
    "microphone": "audio",
    "tablet": "tablets",
    "laptop": "laptops",
    "camera": "cameras",
    "television": "tvs",
    "smart tv": "tvs",
    "tv": "tvs",
    "phone": "phones",
    "smartphone": "phones",
    "refrigerator": "refrigerators",
    "fridge": "refrigerators",
    "freezer": "refrigerators",
    "washing machine": "washers-dryers",
    "washer": "washers-dryers",
    "dryer": "washers-dryers",
    "cooker": "cooking",
    "microwave": "cooking",
    "oven": "cooking",
    "blender": "blenders",
    "juicer": "blenders",
    "kettle": "kettles",
    "toaster": "toasters",
    "iron": "ironing-laundry",
    "inverter": "inverters",
    "solar panel": "solar-panels",
    "solar battery": "solar-batteries",
}

# Fallback keywords for title-based routing when product_type is empty.
# Same keyword set as the WooCommerce discovery — longest-first specificity.
_TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "phones":            ("smartphone", "mobile phone", "iphone"),
    "tablets":           ("tablet", "ipad"),
    "laptops":           ("laptop", "notebook", "macbook", "chromebook"),
    "tvs":               ("smart tv", "television", " tv ", " tv,"),
    "audio":             ("soundbar", "speaker", "headphone", "earphone", "microphone"),
    "cameras":           ("camera", "camcorder", "dslr"),
    "refrigerators":     ("fridge", "refrigerator", "freezer", "sbs"),
    "washers-dryers":    ("washing machine", "washer", "dryer"),
    "cooking":           ("cooker", "microwave oven", "oven", "gas hob"),
    "blenders":          ("blender", "juicer"),
    "kettles":           ("kettle",),
    "toasters":          ("toaster",),
    "ironing-laundry":   ("steam iron", "dry iron", " iron "),
    "inverters":         ("inverter",),
    "solar-panels":      ("solar panel",),
    "solar-batteries":   ("solar battery",),
    "phone-tablet-accessories": ("power bank", "powerbank", "wireless charger",
                                 "charging cable", "smartwatch", "smart watch"),
    "peripherals-accessories":  ("gaming mouse", "usb hub", "keyboard"),
    "console-accessories":      ("dualsense", "xbox controller", "switch pro"),
}


def _classify(product_type: str, title: str) -> str | None:
    """Return the PriceKenya leaf for a Shopify product, or None to drop."""
    pt = (product_type or "").lower().strip()
    if pt:
        # Longest key wins so "power bank" beats "cable".
        best: tuple[int, str | None] = (0, None)
        for key, leaf in PRODUCT_TYPE_TO_LEAF.items():
            if key in pt and len(key) > best[0]:
                best = (len(key), leaf)
        if best[1]:
            return best[1]

    title_l = (title or "").lower()
    best_leaf: str | None = None
    best_len = 0
    for leaf, kws in _TITLE_KEYWORDS.items():
        for kw in kws:
            if kw in title_l and len(kw) > best_len:
                best_leaf = leaf
                best_len = len(kw)
    return best_leaf


def _extract_price(variants: list) -> Decimal | None:
    if not variants:
        return None
    price_str = variants[0].get("price")
    if not price_str:
        return None
    try:
        return Decimal(price_str)
    except Exception:  # noqa: BLE001
        return None


def _extract_image(images: list) -> str | None:
    if not images:
        return None
    return images[0].get("src")


async def fetch_shopify_catalog(
    site_base_url: str, merchant_slug: str, max_pages: int = 30
) -> AsyncIterator[RawListing]:
    """Paginate `<base>/products.json?page=N` and yield RawListing for every
    product we can route to a PriceKenya leaf. Stops when a page returns
    zero products or a network error.
    """
    base = site_base_url.rstrip("/")
    # curl_cffi with Chrome TLS impersonation — plain httpx used to work
    # from residential IPs but Digital City started returning empty
    # /products.json responses to GitHub Actions runner ranges on
    # 2026-07-16 (silent 0-yield instead of a challenge page). Chrome
    # impersonation makes the request indistinguishable from a real
    # browser regardless of source IP.
    client = CffiPoliteClient()
    # One-shot diagnostic on the FIRST page only — if page 1 comes back
    # empty (or errors), log the status + head of the body so CI tells us
    # whether it's IP-blocking, a WAF challenge, or a real empty catalog.
    # Silent zero-yield is the worst failure mode to debug blind.
    try:
        for page in range(1, max_pages + 1):
            url = f"{base}/products.json?limit=250&page={page}"
            try:
                r = await client.get(url)
            except Exception as exc:  # noqa: BLE001
                if page == 1:
                    print(f"[shopify] {merchant_slug} page1 GET raised: {exc!r}")
                return
            if r.status_code >= 400:
                if page == 1:
                    print(f"[shopify] {merchant_slug} page1 HTTP {r.status_code}: {r.text[:300]!r}")
                return
            try:
                data = json.loads(r.text)
            except Exception:  # noqa: BLE001 — WAF page or truncated JSON
                if page == 1:
                    print(f"[shopify] {merchant_slug} page1 non-JSON (status {r.status_code}): {r.text[:300]!r}")
                return
            products = data.get("products", [])
            if not products:
                if page == 1:
                    print(f"[shopify] {merchant_slug} page1 empty products[] (status {r.status_code}, body head): {r.text[:300]!r}")
                return
            for p in products:
                title = (p.get("title") or "").strip()
                if not title:
                    continue
                leaf = _classify(p.get("product_type", ""), title)
                if not leaf:
                    continue  # nothing sensible to route this to
                price = _extract_price(p.get("variants", []))
                if price is None or price <= 0:
                    continue
                handle = p.get("handle") or ""
                description = _strip_html(p.get("body_html") or "") or None
                yield RawListing(
                    merchant_slug=merchant_slug,
                    merchant_sku=str(p.get("id")) if p.get("id") is not None else None,
                    url=f"{base}/products/{handle}",
                    title=title,
                    price_kes=price,
                    in_stock=bool(p.get("variants", [{}])[0].get("available", True)),
                    image_url=_extract_image(p.get("images", [])),
                    category_slug=leaf,
                    description=description,
                )
    finally:
        await client.aclose()
