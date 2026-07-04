"""Kilimall Kenya scraper.

Kilimall is a Nuxt SPA that server-renders 36 cards/page. Category URLs
(/category/...) return HTTP 500 for anonymous requests, so we use the search
endpoint (?q=<query>) which does work.

Image URLs are not on the SSR'd `<img>` tags (Kilimall attaches them via JS
after hydration) but ARE embedded in the Nuxt state script as a flattened
array: `,<listing_id>,"<image_url>",<price>,<original_price>,"<title>",...`
_build_image_map extracts that positional pairing so listings land with
their real thumbnail.
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

_PRICE_RE = re.compile(r"[\d,]+")
_LISTING_ID_RE = re.compile(r"/listing/(\d+)-")
# Matches the Nuxt hydration tuple  ,<listing_id>,"<image_url>",<price>,...
# Constraints on the pieces are loose enough to survive Kilimall CDN URL shape
# changes, tight enough that random 10-digit numbers in the page can't collide.
_NUXT_TUPLE_RE = re.compile(
    r',(\d{9,12}),"(https://(?:img|image)\.kilimall\.com/[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"',
    re.IGNORECASE,
)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _parse_price(raw: str) -> Decimal | None:
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _build_image_map(raw_html: str) -> dict[str, str]:
    """Return {listing_id: image_url} from the Nuxt SSR state.

    Each product tuple in the flattened Nuxt payload starts with the listing
    ID as an unquoted integer, immediately followed by the primary image URL
    string. If Kilimall changes its payload shape the map will just come back
    empty — the scraper still yields listings, just without images.
    """
    m: dict[str, str] = {}
    for match in _NUXT_TUPLE_RE.finditer(raw_html):
        listing_id, url = match.group(1), match.group(2)
        # Preserve first URL if the same listing appears twice.
        m.setdefault(listing_id, url)
    return m


async def _fetch_og_image(client: PoliteClient, product_url: str) -> str | None:
    """Last-resort image lookup: fetch the product detail page and read og:image.

    Used only when the Nuxt state didn't include an image for a listing (Kilimall's
    payload shape isn't 100% consistent across sellers). Cost is one extra HTTP
    request per missing-image listing per scrape — cheap because most listings hit
    the Nuxt fast-path.
    """
    try:
        resp = await client.get(product_url)
    except Exception:  # noqa: BLE001
        return None
    m = _OG_IMAGE_RE.search(resp.text)
    return m.group(1) if m else None


async def _fetch_search(
    query: str, max_pages: int, category_slug: str
) -> AsyncIterator[RawListing]:
    client = PoliteClient()
    try:
        for page in range(1, max_pages + 1):
            url = f"https://www.kilimall.co.ke/search?q={query}&page={page}"
            resp = await client.get(url)
            image_map = _build_image_map(resp.text)
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
                product_url = (
                    href if href.startswith("http") else f"https://www.kilimall.co.ke{href}"
                )
                price = _parse_price(price_node.text(strip=True))
                if price is None:
                    continue
                sku = None
                m = _LISTING_ID_RE.search(href)
                if m:
                    sku = m.group(1)
                image_url = image_map.get(sku) if sku else None
                if not image_url:
                    image_url = await _fetch_og_image(client, product_url)
                yield RawListing(
                    merchant_slug=MERCHANT_SLUG,
                    merchant_sku=sku,
                    url=product_url,
                    title=title_node.text(strip=True),
                    price_kes=price,
                    in_stock=True,
                    image_url=image_url,
                    category_slug=category_slug,
                )
    finally:
        await client.aclose()


async def fetch_phones() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("smartphone", 6, "phones"):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("laptop", 6, "laptops"):
        yield r


async def fetch_tvs() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("tv", 6, "tvs"):
        yield r


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("refrigerator", 6, "refrigerators"):
        yield r


async def fetch_washers_dryers() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("washing machine", 6, "washers-dryers"):
        yield r


async def fetch_cooking() -> AsyncIterator[RawListing]:
    """Cookers + microwaves via two searches; matcher unifies into 'cooking'."""
    async for r in _fetch_search("microwave", 4, "cooking"):
        yield r
    async for r in _fetch_search("cooker", 4, "cooking"):
        yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    """Broad audio coverage across four search queries."""
    for query in ("soundbar", "home theatre", "bluetooth speaker", "earbuds"):
        async for r in _fetch_search(query, 4, "audio"):
            yield r


async def fetch_cameras() -> AsyncIterator[RawListing]:
    """Camera coverage across the main types (broader queries return more
    accessories, but the matcher filters them out)."""
    for query in ("digital camera", "action camera", "cctv camera", "dslr"):
        async for r in _fetch_search(query, 4, "cameras"):
            yield r


async def fetch_blenders() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("blender", 4, "blenders"):
        yield r


async def fetch_toasters() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("toaster", 4, "toasters"):
        yield r


async def fetch_kettles() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("electric kettle", 4, "kettles"):
        yield r


async def fetch_irons() -> AsyncIterator[RawListing]:
    async for r in _fetch_search("clothes iron", 4, "ironing-laundry"):
        yield r
