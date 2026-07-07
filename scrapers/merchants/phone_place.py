"""Phone Place Kenya scraper.

Phone Place runs a heavily customised WooCommerce theme behind Cloudflare with
TLS fingerprinting — same wall as Naivas — so we fetch through
CffiPoliteClient rather than the shared `fetch_woocommerce_category` helper,
which uses plain httpx.

Structure of a category page:
- Standard WooCommerce URL scheme: `/product-category/<slug>/` with pagination
  at `/page/N/`. Past the last page the site returns 404 — our natural stop.
- The theme wraps each product in a `.product-wrapper` inside the main
  `.products` container. Widget carousels elsewhere on the page also use
  `.product-wrapper`, which is why we scope to `.products` first.
- Per card:
    - Title: `<img alt="...">` (the theme moves the title into image alt)
    - Product URL: `<a href*="/product/">`
    - Price: sibling of `.product-wrapper` under its parent, `.price bdi`
    - Image: `img[data-src]` (lazy-loaded — plain `src` is an inline SVG placeholder)
    - SKU: any descendant with `data-product_id`

Phone Place is phones-heavy but also carries audio, cameras, laptops (Apple),
gaming, and mobile-phone accessories, so LEAF_TO_URLS covers each of those
PriceKenya leaves. Smartphones alone is 60/page × 3+ pages = ~180 listings.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.base import CffiPoliteClient, RawListing

MERCHANT_META = {
    "slug": "phoneplace-ke",
    "name": "Phone Place Kenya",
    "base_url": "https://www.phoneplacekenya.com",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

LEAF_TO_URLS: dict[str, list[str]] = {
    "phones": [
        "https://www.phoneplacekenya.com/product-category/smartphones/",
        "https://www.phoneplacekenya.com/product-category/apple/iphone/",
        "https://www.phoneplacekenya.com/product-category/infinix-phones-in-kenya/",
    ],
    "laptops": [
        "https://www.phoneplacekenya.com/product-category/laptops/macbooks/",
        "https://www.phoneplacekenya.com/product-category/laptops/imac/",
    ],
    "audio": [
        "https://www.phoneplacekenya.com/product-category/audio/headphones/",
        "https://www.phoneplacekenya.com/product-category/audio/speakers/",
        "https://www.phoneplacekenya.com/product-category/audio/soundbar/",
        "https://www.phoneplacekenya.com/product-category/audio/buds/",
        "https://www.phoneplacekenya.com/product-category/audio/microphones/",
    ],
    "cameras": [
        "https://www.phoneplacekenya.com/product-category/cameras/action-cameras/",
        "https://www.phoneplacekenya.com/product-category/cameras/drone/",
    ],
    "phone-tablet-accessories": [
        "https://www.phoneplacekenya.com/product-category/mobile-phone-accessories/chargers/",
        "https://www.phoneplacekenya.com/product-category/mobile-phone-accessories/powerbank/",
        "https://www.phoneplacekenya.com/product-category/mobile-phone-accessories/phone-covers/",
        "https://www.phoneplacekenya.com/product-category/mobile-phone-accessories/protectors/",
        "https://www.phoneplacekenya.com/product-category/mobile-phone-accessories/smartwatches/",
    ],
    "console-accessories": [
        "https://www.phoneplacekenya.com/product-category/gaming/gaming-controllers/",
        "https://www.phoneplacekenya.com/product-category/gaming/gaming-headsets/",
    ],
    # gaming-console / ps5-games are actual game consoles + software, not
    # accessories. Left here for a future gaming-consoles leaf; today no
    # matcher exists for the "gaming" category so ingest silently drops.
    "gaming": [
        "https://www.phoneplacekenya.com/product-category/gaming/gaming-console/",
        "https://www.phoneplacekenya.com/product-category/gaming/ps5-games/",
    ],
}

_PRICE_RE = re.compile(r"[\d,]+")
_MAX_PAGES = 30


def _parse_price(raw: str) -> Decimal | None:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _extract_from_card(card, container, category_slug: str) -> RawListing | None:
    """Extract one listing. `container` is the enclosing element in the main
    `.products` list — needed because the theme puts the price outside the
    `.product-wrapper` but inside the same product cell."""
    a = card.css_first('a[href*="/product/"]')
    img = card.css_first("img")
    if not (a and img):
        return None
    product_url = a.attributes.get("href", "")
    if not product_url.startswith("http"):
        product_url = "https://www.phoneplacekenya.com" + product_url

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
        # Placeholder — pull the srcset first entry instead
        srcset = img.attributes.get("data-srcset") or ""
        image_url = srcset.split()[0] if srcset else None

    # Merchant SKU lives on a descendant with data-product_id
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
    client: CffiPoliteClient, base_url: str, category_slug: str
) -> AsyncIterator[RawListing]:
    for page in range(1, _MAX_PAGES + 1):
        url = base_url.rstrip("/") + "/"
        if page > 1:
            url = url + f"page/{page}/"
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001
            # 404 past the last page is expected — stop cleanly.
            return
        tree = HTMLParser(resp.text)
        main = tree.css_first(".products")
        if not main:
            return
        cards = main.css(".product-wrapper")
        if not cards:
            return
        for card in cards:
            # The .product-wrapper is inside a per-product container; walk up
            # to find the enclosing cell so we can reach the price node that
            # sits next to it.
            container = card.parent or card
            listing = _extract_from_card(card, container, category_slug)
            if listing:
                yield listing


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


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _fetch_one("phones"):
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
