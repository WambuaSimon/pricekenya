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
            try:
                resp = await client.get(url)
            except Exception:  # noqa: BLE001
                # Skip the flaky page; previous pages already yielded.
                continue
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
    async for r in _fetch_category("https://www.jumia.co.ke/smartphones/?page={page}", 8, "phones"):
        yield r


async def fetch_tablets() -> AsyncIterator[RawListing]:
    """Jumia files tablets under two URLs — /other-tablets/ (Android + generic)
    and /ipads/ (Apple). We hit both; matcher dedupes by canonical_key."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/other-tablets/?page={page}", 6, "tablets"
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/ipads/?page={page}", 4, "tablets"
    ):
        yield r


async def fetch_laptops() -> AsyncIterator[RawListing]:
    async for r in _fetch_category("https://www.jumia.co.ke/laptops/?page={page}", 8, "laptops"):
        yield r


async def fetch_tvs() -> AsyncIterator[RawListing]:
    async for r in _fetch_category("https://www.jumia.co.ke/televisions/?page={page}", 8, "tvs"):
        yield r


async def fetch_refrigerators() -> AsyncIterator[RawListing]:
    # Jumia redirects /refrigerators/ to this canonical URL but drops the
    # query string in the redirect, so hitting the canonical URL directly is
    # what actually paginates.
    async for r in _fetch_category(
        "https://www.jumia.co.ke/appliances-fridges-freezers/?page={page}",
        8,
        "refrigerators",
    ):
        yield r


async def fetch_washers_dryers() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/appliances-washers-dryers/?page={page}",
        8,
        "washers-dryers",
    ):
        yield r


async def fetch_cooking() -> AsyncIterator[RawListing]:
    """Cookers + microwaves. Jumia files them under separate URLs but the
    matcher unifies them into the "cooking" leaf."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/cookers/?page={page}", 6, "cooking"
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/small-appliances-microwave/?page={page}",
        6,
        "cooking",
    ):
        yield r


async def fetch_audio() -> AsyncIterator[RawListing]:
    """Home audio, speakers, soundbars, headphones — Jumia splits these across
    a few URLs. Matcher routes each listing by device-type keyword."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/home-audio-electronics/?page={page}",
        4,
        "audio",
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/home-audio-speakers/?page={page}",
        4,
        "audio",
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/portable-audio-video/?page={page}",
        4,
        "audio",
    ):
        yield r


async def fetch_cameras() -> AsyncIterator[RawListing]:
    """Jumia files cameras (real + generic imports) under two URLs. The
    matcher rejects the accessories that leak in."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/cameras/?page={page}", 4, "cameras"
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/electronics-cameras-digital-cameras/?page={page}",
        4,
        "cameras",
    ):
        yield r


async def fetch_blenders() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/blenders/?page={page}", 6, "blenders"
    ):
        yield r


async def fetch_toasters() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/toasters/?page={page}", 6, "toasters"
    ):
        yield r


async def fetch_kettles() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/kettles/?page={page}", 6, "kettles"
    ):
        yield r


async def fetch_irons() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/irons/?page={page}", 6, "ironing-laundry"
    ):
        yield r


async def fetch_inverters() -> AsyncIterator[RawListing]:
    """Jumia has a dedicated /inverters/ landing. Solar-focused inverters also
    surface via search — we hit both so we get the specialist listings that
    the flat category page doesn't rank."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/inverters/?page={page}", 6, "inverters"
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/catalog/?q=solar+inverter&page={page}",
        4,
        "inverters",
    ):
        yield r


async def fetch_solar_panels() -> AsyncIterator[RawListing]:
    async for r in _fetch_category(
        "https://www.jumia.co.ke/solar-panels/?page={page}", 6, "solar-panels"
    ):
        yield r


async def fetch_consoles() -> AsyncIterator[RawListing]:
    """Jumia has no working umbrella /consoles/ landing (`/video-game-
    consoles/` is a controllers page, `/consoles/` is retro handhelds).
    Real console SKUs surface via catalog search — one search per family
    for good recall. Each title is dispatched to the right console leaf
    via the router; retro clones / accessories / games silently drop.
    """
    from scrapers.common.console_router import classify_console_leaf

    seen: set[str] = set()
    for search in (
        "https://www.jumia.co.ke/catalog/?q=playstation+5&page={page}",
        "https://www.jumia.co.ke/catalog/?q=xbox+series&page={page}",
        "https://www.jumia.co.ke/catalog/?q=nintendo+switch&page={page}",
    ):
        async for r in _fetch_category(search, 4, "_pending"):
            if r.url in seen:
                continue
            seen.add(r.url)
            leaf = classify_console_leaf(r.title)
            if leaf:
                r.category_slug = leaf
                yield r


async def fetch_solar_batteries() -> AsyncIterator[RawListing]:
    """No dedicated Jumia category for solar batteries — we rely on catalog
    search. Matcher rejects car / AA / cmos batteries so the noise is bounded."""
    async for r in _fetch_category(
        "https://www.jumia.co.ke/catalog/?q=solar+battery&page={page}",
        4,
        "solar-batteries",
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/catalog/?q=lithium+battery&page={page}",
        4,
        "solar-batteries",
    ):
        yield r
    async for r in _fetch_category(
        "https://www.jumia.co.ke/catalog/?q=deep+cycle+battery&page={page}",
        4,
        "solar-batteries",
    ):
        yield r
