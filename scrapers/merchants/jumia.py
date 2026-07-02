"""Jumia Kenya scraper.

Jumia serves clean, static HTML with stable selectors (`article.prd`, `.name`,
`.prc`, `img.img`) across categories. We only need one selector-based parser
and a per-category URL. The polite UA in `settings.scraper_user_agent` is
important — Mozilla-style UAs get 403 from Jumia's WAF; ours don't.
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

_PRICE_RE = re.compile(r"[\d,]+")


def _parse_price(raw: str) -> Decimal | None:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


async def _fetch_category(
    url_pattern: str, max_pages: int, category_slug: str
) -> AsyncIterator[RawListing]:
    client = PoliteClient()
    try:
        for page in range(1, max_pages + 1):
            url = url_pattern.format(page=page)
            resp = await client.get(url)
            html = HTMLParser(resp.text)
            cards = html.css("article.prd")
            if not cards:
                return  # layout drift or block — stop quietly
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
                    image_url=(
                        img_node.attributes.get("data-src") or img_node.attributes.get("src")
                    )
                    if img_node
                    else None,
                    category_slug=category_slug,
                )
    finally:
        await client.aclose()


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _fetch_category("https://www.jumia.co.ke/smartphones/?page={page}", 3, "phones"):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _fetch_category("https://www.jumia.co.ke/laptops/?page={page}", 3, "laptops"):
        yield r


async def fetch_tvs() -> AsyncIterator[RawListing]:
    async for r in _fetch_category("https://www.jumia.co.ke/televisions/?page={page}", 3, "tvs"):
        yield r


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    # Jumia redirects /refrigerators/ to this canonical URL but drops the
    # query string in the redirect, so hitting the canonical URL directly is
    # what actually paginates.
    async for r in _fetch_category(
        "https://www.jumia.co.ke/appliances-fridges-freezers/?page={page}",
        3,
        "refrigerators",
    ):
        yield r


async def fetch_washers_dryers() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/appliances-washers-dryers/?page={page}",
        3,
        "washers-dryers",
    ):
        yield r


async def fetch_cooking() -> AsyncIterator[RawListing]:
    """Cookers + microwaves. Jumia files them under separate URLs but the
    matcher unifies them into the "cooking" leaf."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/cookers/?page={page}", 2, "cooking"
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/small-appliances-microwave/?page={page}",
        2,
        "cooking",
    ):
        yield r
