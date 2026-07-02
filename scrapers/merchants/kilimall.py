"""Kilimall Kenya phones scraper.

Kilimall is a Nuxt SPA that server-renders 36 cards/page. Category URLs
(/category/mobile-phones) return HTTP 500 for anonymous requests, but the search
endpoint (?q=smartphone) works and returns clean HTML.

Known gap: image URLs are lazy-loaded via JS and not present in the initial
HTML, so listings from Kilimall land without images for now. Cross-merchant
matching (the main point) is unaffected. To fill images later, either parse the
window.__NUXT__ JSON blob in the SSR'd HTML or fetch each product detail page.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "kilimall-ke",
    "name": "Kilimall Kenya",
    "base_url": "https://www.kilimall.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
SEARCH_URL = "https://www.kilimall.co.ke/search?q=smartphone&page={page}"
MAX_PAGES = 3

_PRICE_RE = re.compile(r"[\d,]+")
_LISTING_ID_RE = re.compile(r"/listing/(\d+)-")


def _parse_price(raw: str) -> Decimal | None:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


async def fetch_phones() -> AsyncIterator[RawListing]:
    client = PoliteClient()
    try:
        for page in range(1, MAX_PAGES + 1):
            url = SEARCH_URL.format(page=page)
            resp = await client.get(url)
            html = HTMLParser(resp.text)
            cards = html.css(".product-item")
            if not cards:
                return
            for card in cards:
                a = card.css_first('a[href*="/listing/"]')
                title_node = card.css_first(".product-title")
                price_node = card.css_first(".product-price")
                if not (a and title_node and price_node):
                    continue
                href = a.attributes.get("href", "")
                product_url = href if href.startswith("http") else f"https://www.kilimall.co.ke{href}"
                price = _parse_price(price_node.text(strip=True))
                if price is None:
                    continue
                sku = None
                m = _LISTING_ID_RE.search(href)
                if m:
                    sku = m.group(1)
                yield RawListing(
                    merchant_slug=MERCHANT_SLUG,
                    merchant_sku=sku,
                    url=product_url,
                    title=title_node.text(strip=True),
                    price_kes=price,
                    in_stock=True,
                    image_url=None,
                    category_slug="phones",
                )
    finally:
        await client.aclose()
