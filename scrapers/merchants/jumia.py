"""Jumia Kenya phones scraper.

NOTE: This is a v0 reference implementation. Jumia's HTML changes; selectors will
need to be revisited. The category and pagination URLs are intentionally
parameterised so they can be tweaked without code changes elsewhere.

If Jumia blocks the IP or serves a JS-only page, swap PoliteClient for a
Playwright-based fetch in this file — the public function signature stays the
same.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "jumia-ke",
    "name": "Jumia Kenya",
    "base_url": "https://www.jumia.co.ke",
}
MERCHANT_SLUG = MERCHANT_META["slug"]
CATEGORY_URL = "https://www.jumia.co.ke/smartphones/?page={page}"
MAX_PAGES = 3  # v0: keep small until we're sure we're not being blocked

_PRICE_RE = re.compile(r"[\d,]+")


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
            url = CATEGORY_URL.format(page=page)
            resp = await client.get(url)
            html = HTMLParser(resp.text)
            cards = html.css("article.prd")
            if not cards:
                # Layout drift or block — stop quietly rather than burning pages.
                return
            for card in cards:
                a = card.css_first("a.core")
                if not a:
                    continue
                href = a.attributes.get("href", "")
                product_url = href if href.startswith("http") else f"https://www.jumia.co.ke{href}"
                title_node = card.css_first(".name")
                price_node = card.css_first(".prc")
                img_node = card.css_first("img.img")
                if not (title_node and price_node):
                    continue
                price = _parse_price(price_node.text(strip=True))
                if price is None:
                    continue
                yield RawListing(
                    merchant_slug=MERCHANT_SLUG,
                    merchant_sku=card.attributes.get("data-sku"),
                    url=product_url,
                    title=title_node.text(strip=True),
                    price_kes=price,
                    in_stock=True,
                    image_url=(img_node.attributes.get("data-src") or img_node.attributes.get("src"))
                    if img_node
                    else None,
                    category_slug="phones",
                )
    finally:
        await client.aclose()
