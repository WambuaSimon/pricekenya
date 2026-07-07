"""MyBigOrder Kenya scraper.

MyBigOrder (mybigorder.com) is a Kenyan multi-vendor marketplace. It runs a
server-rendered PHP storefront ("Active eCommerce CMS" — same template family
as many Bagisto/CS-Cart forks). No Cloudflare wall, no TLS fingerprinting;
plain httpx via `PoliteClient` gets through fine. Prices are already in KSh.

**URL structure:**
- Category listings: `/category/<slug>` with `?page=N` pagination.
- Product pages: `/product/<slug>`.

**Pagination quirk:** the on-page paginator only exposes page=2, but higher
page numbers still return 200 with a "featured/recommended" bloc of ~36
products that also appear on page 1. In other words, once we've walked past
the last real page, the site keeps serving the featured bloc forever. We
dedupe by product URL and stop when a page adds zero new URLs.

**Card structure** (regex-parsed — the container has a stable class combo
even across categories):
- Container: `<div class="col border-right border-bottom has-transition hov-shadow-out z-1">`
- Product URL: first `<a href="/product/<slug>" ...` inside the card.
- Image URL: the `<img class="lazyload ..." src="...">` sibling in the image `<a>`.
- Title: `alt="..."` on that same `<img>` (title attr also carries it).
- SKU: `onclick="addToWishList(<id>)"` — the marketplace product id.
- Price: `<span class="fw-700 text-primary">KSh<amount></span>`.
- Optional discount: `<del class="fw-400 text-secondary mr-1">KSh<old></del>`.

**Category routing:** Unlike QuickMart's single feed, MyBigOrder exposes
one URL per subcategory. Most PriceKenya leaves map 1:1 to a MyBigOrder
subcategory slug (see `_LEAF_TO_URL`), so we set `category_slug` at fetch
time. The two mixed appliance buckets (large/small) need title-keyword
routing because they aggregate fridges + washers + freezers + water
dispensers (large) and kettles + toasters + irons + blenders (small).
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import AsyncIterator
from decimal import Decimal

from scrapers.common.base import PoliteClient, RawListing

MERCHANT_META = {
    "slug": "mybigorder-ke",
    "name": "MyBigOrder Kenya",
    "base_url": "https://mybigorder.com",
}
MERCHANT_SLUG = MERCHANT_META["slug"]

_BASE = "https://mybigorder.com"

# PriceKenya leaf → MyBigOrder category slug. One URL per leaf where the
# marketplace's own taxonomy already lines up; the two mixed buckets are
# handled separately below with title-based routing.
_LEAF_TO_URL: dict[str, str] = {
    "phones": "mobile-phones-2nrkr",
    "tablets": "tablets-krf7b",
    "phone-tablet-accessories": "phone-accessories-n24ys",
    "laptops": "laptops-vw5gf",
    "tvs": "televisions-u1yat",
    "cameras": "cameras-safbg",
    "audio": "audio--video-devices-j36yo",
    "cooking": "cooking-appliances-chk77",
}

# Mixed buckets — scrape each once and let title keywords assign the leaf.
# First-match-wins, so order matters: put more specific patterns first.
_MIXED_CATEGORY_URLS: list[str] = [
    "large-appliances-txwkq",
    "small-appliances-zf9qd",
]

_TITLE_KEYWORD_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bkettle\b", re.I), "kettles"),
    (re.compile(r"\b(?:toaster|sandwich\s+maker|bread\s+maker)\b", re.I), "toasters"),
    (re.compile(r"\b(?:steam\s+iron|dry\s+iron|iron\s+box|ironing)\b", re.I), "ironing-laundry"),
    (re.compile(r"\b(?:blender|juicer|food\s+processor|mixer\s+grinder)\b", re.I), "blenders"),
    (re.compile(r"\bwater\s+dispenser\b", re.I), "water-dispensers-coolers"),
    (re.compile(r"\bfreezer\b", re.I), "freezers"),
    (re.compile(r"\b(?:fridge|refrigerator)\b", re.I), "refrigerators"),
    (re.compile(r"\b(?:washing\s+machine|dryer|dishwasher)\b", re.I), "washers-dryers"),
    (re.compile(r"\b(?:microwave|oven|cooker)\b", re.I), "cooking"),
]

# We cap page iteration to guard against a category that never trips the
# "no new URLs" stop (site changes, category with genuinely 500+ pages).
_MAX_PAGES_PER_CATEGORY = 20

_CARD_MARKER = (
    '<div class="col border-right border-bottom has-transition hov-shadow-out z-1">'
)
_PRODUCT_URL_RE = re.compile(
    r'href="(https://mybigorder\.com/product/[^"?#]+)"'
)
_IMG_TITLE_RE = re.compile(
    r'<img[^>]*?class="lazyload[^"]*"[^>]*?src="([^"]+)"[^>]*?alt="([^"]+)"',
    re.DOTALL,
)
_SKU_RE = re.compile(r'addToWishList\((\d+)\)')
_PRICE_RE = re.compile(
    r'<span class="fw-700 text-primary">KSh([\d,]+\.\d{2})'
)


def _parse_price(raw: str) -> Decimal | None:
    try:
        v = Decimal(raw.replace(",", "").strip())
    except Exception:  # noqa: BLE001
        return None
    if v <= 0:
        return None
    return v


def _iter_card_positions(page_html: str):
    start = 0
    while True:
        idx = page_html.find(_CARD_MARKER, start)
        if idx == -1:
            return
        yield idx
        start = idx + len(_CARD_MARKER)


def _route_by_title(title: str) -> str | None:
    for pattern, slug in _TITLE_KEYWORD_RULES:
        if pattern.search(title):
            return slug
    return None


def _parse_cards(
    page_html: str,
    *,
    fixed_category_slug: str | None,
) -> list[RawListing]:
    """Parse product cards out of one category page.

    `fixed_category_slug` is set when the merchant's category maps 1:1 to a
    PriceKenya leaf. When it's None (mixed appliance buckets) we route each
    card by title keyword and skip anything that doesn't match.
    """
    positions = list(_iter_card_positions(page_html))
    if not positions:
        return []
    listings: list[RawListing] = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else start + 6000
        card = page_html[start:end]

        url_m = _PRODUCT_URL_RE.search(card)
        img_m = _IMG_TITLE_RE.search(card)
        price_m = _PRICE_RE.search(card)
        if not url_m or not img_m or not price_m:
            continue

        title = html_lib.unescape(img_m.group(2)).strip()
        image_url = img_m.group(1).strip()
        # Skip the placeholder — telling the frontend to render "no image" is
        # cleaner than showing an obviously-empty placeholder.
        if image_url.endswith("/placeholder.jpg"):
            image_url_final: str | None = None
        else:
            image_url_final = image_url

        price = _parse_price(price_m.group(1))
        if not price:
            continue

        category_slug = fixed_category_slug or _route_by_title(title)
        if not category_slug:
            # Mixed bucket + no keyword match — skip.
            continue

        sku_m = _SKU_RE.search(card)

        listings.append(
            RawListing(
                merchant_slug=MERCHANT_SLUG,
                merchant_sku=sku_m.group(1) if sku_m else None,
                url=url_m.group(1).strip(),
                title=title,
                price_kes=price,
                in_stock=True,
                image_url=image_url_final,
                category_slug=category_slug,
            )
        )
    return listings


async def _fetch_category(
    client: PoliteClient,
    slug: str,
    *,
    fixed_category_slug: str | None,
    seen: set[str],
) -> AsyncIterator[RawListing]:
    url = f"{_BASE}/category/{slug}"
    for page in range(1, _MAX_PAGES_PER_CATEGORY + 1):
        page_url = url if page == 1 else f"{url}?page={page}"
        try:
            resp = await client.get(page_url)
        except Exception as e:  # noqa: BLE001
            # Any failure — 4xx/5xx after retries, network timeout, whatever
            # — is scoped to this category. Log and move on. Killing the whole
            # `all-mybigorder` matrix job because one subcategory got removed
            # or throttled is a bigger problem than losing that subcategory's
            # data for one cron cycle.
            print(f"mybigorder: {slug} page {page} failed ({e.__class__.__name__}); "
                  f"skipping rest of this category")
            return
        listings = _parse_cards(resp.text, fixed_category_slug=fixed_category_slug)
        new_this_page = 0
        for r in listings:
            if r.url in seen:
                continue
            seen.add(r.url)
            new_this_page += 1
            yield r
        # Stop as soon as a page adds nothing new — MyBigOrder keeps serving
        # a featured bloc past the last real page, so this is the natural
        # end signal.
        if new_this_page == 0 and page > 1:
            return


async def _fetch_all(client: PoliteClient) -> AsyncIterator[RawListing]:
    seen: set[str] = set()
    # 1:1 mappings first.
    for leaf_slug, mbo_slug in _LEAF_TO_URL.items():
        async for r in _fetch_category(
            client,
            mbo_slug,
            fixed_category_slug=leaf_slug,
            seen=seen,
        ):
            yield r
    # Mixed buckets — route by title.
    for mbo_slug in _MIXED_CATEGORY_URLS:
        async for r in _fetch_category(
            client,
            mbo_slug,
            fixed_category_slug=None,
            seen=seen,
        ):
            yield r


async def fetch_all() -> AsyncIterator[RawListing]:
    client = PoliteClient()
    try:
        async for r in _fetch_all(client):
            yield r
    finally:
        await client.aclose()
