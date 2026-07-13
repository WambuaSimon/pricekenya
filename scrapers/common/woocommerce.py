"""Shared WooCommerce scraping helper.

Most Kenyan WordPress shops use the standard WooCommerce theme structure:
    <li class="product">
      <a href="...">
        <img src="...">
        <h2 class="woocommerce-loop-product__title">Title</h2>
        <span class="price"><bdi>KSh 12,345</bdi></span>
      </a>
    </li>

Pagination is standard `/page/<N>/`. This helper handles the fetch + parse
so each merchant module is just merchant metadata + a leaf → URL map.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.base import CffiPoliteClient, PlaywrightPoliteClient, PoliteClient, RawListing

_PRICE_RE = re.compile(r"[\d,]+")

# Known WooCommerce lazy-load / preloader placeholders. Merchants inject these
# into <img src> and put the real URL in data-src / data-lazy-src. If we
# accidentally pick up the placeholder as the product image, the shopper sees
# an animated "loading" GIF that never resolves.
_PLACEHOLDER_MARKERS = (
    "prod_loading",       # Avechi's Merto theme
    "loading.gif",
    "loader.gif",
    "placeholder.png",
    "placeholder.jpg",
    "placeholder.svg",
    "blank.gif",
    "blank.png",
    "no-image",
    "noimage",
    "spinner.gif",
    "spacer.gif",
    "spacer.png",
)


def is_placeholder_image(url: str | None) -> bool:
    """True when the URL looks like a lazy-load placeholder rather than a
    real product photo."""
    if not url:
        return False
    lower = url.lower()
    if lower.startswith("data:image") or "svg+xml" in lower:
        return True
    return any(marker in lower for marker in _PLACEHOLDER_MARKERS)


def _first_real_image(*candidates: str | None) -> str | None:
    """Return the first candidate that's non-empty AND not a placeholder."""
    for c in candidates:
        if c and not is_placeholder_image(c):
            return c
    return None


def _parse_price(raw: str) -> Decimal | None:
    """Grab the first number-run out of a WooCommerce price string like
    'KSh 12,345' or 'KShs 45,000.00' or 'KSh 12,000 – KSh 15,000'."""
    m = _PRICE_RE.search(raw or "")
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except Exception:  # noqa: BLE001
        return None


def _extract_product(card, base_url: str, merchant_slug: str, category_slug: str) -> RawListing | None:
    a = card.css_first("a[href]")
    # WooCommerce default is .woocommerce-loop-product__title (h2), but themes
    # customize this heavily. Avechi uses h3.product-name, iStore uses the
    # default, Gadget World is close to default. Try known customizations
    # before falling back to any h2/h3 in the card, and as a last resort the
    # img alt attribute — Patabay's theme (and Phone Place's card variant)
    # ship the visible product name only via img alt, no text-title element.
    title_node = (
        card.css_first(".woocommerce-loop-product__title")
        or card.css_first(".product-name")
        or card.css_first(".product-title")
        or card.css_first("h2")
        or card.css_first("h3")
    )
    price_node = (
        card.css_first(".price bdi")
        or card.css_first(".price ins bdi")
        or card.css_first(".price .amount")
        or card.css_first(".price")
    )
    img = card.css_first("img")
    if not (a and price_node):
        return None
    href = a.attributes.get("href", "")
    product_url = href if href.startswith("http") else base_url.rstrip("/") + href
    title = title_node.text(strip=True) if title_node else ""
    if not title and img:
        title = (img.attributes.get("alt") or "").strip()
    if not title:
        return None
    price = _parse_price(price_node.text(strip=True))
    if price is None or price <= 0:
        return None
    image_url: str | None = None
    if img:
        # Try lazy-load attributes BEFORE `src`. On Avechi and many other
        # Merto/WoodMart-style themes, `src` is a placeholder GIF and the
        # real URL lives in `data-src`. Precedence matters — this used to
        # be an `if/else` ternary chained with `or` that silently dropped
        # the `data-src` fallback whenever `data-srcset` was absent.
        srcset_first = None
        srcset_raw = img.attributes.get("data-srcset") or ""
        if srcset_raw:
            srcset_first = srcset_raw.split()[0]
        image_url = _first_real_image(
            img.attributes.get("data-lazy-src"),
            img.attributes.get("data-src"),
            srcset_first,
            img.attributes.get("src"),
        )
    return RawListing(
        merchant_slug=merchant_slug,
        merchant_sku=None,
        url=product_url,
        title=title,
        price_kes=price,
        in_stock=True,
        image_url=image_url,
        category_slug=category_slug,
    )


async def fetch_woocommerce_category(
    category_base_url: str,
    max_pages: int,
    merchant_slug: str,
    category_slug: str,
    site_base_url: str,
    client_type: str = "polite",
) -> AsyncIterator[RawListing]:
    """Iterate a WooCommerce category page + `/page/N/` up to `max_pages`.

    Yields RawListing for each product card found. Silently stops when a
    page returns no cards (layout drift or last-page-reached).

    `client_type="cffi"` switches to CffiPoliteClient for Cloudflare-shielded
    merchants that fingerprint TLS (403 on plain httpx). `client_type=
    "playwright"` swaps in a headless-Chromium client for merchants that
    also require JS-challenge resolution (Cloudflare Turnstile etc.).
    Default stays polite httpx so existing callers don't change behaviour.
    """
    if client_type == "playwright":
        client = PlaywrightPoliteClient()
    elif client_type == "playwright-stealth":
        client = PlaywrightPoliteClient(stealth=True)
    elif client_type == "cffi":
        client = CffiPoliteClient()
    else:
        client = PoliteClient()
    try:
        for page in range(1, max_pages + 1):
            url = category_base_url.rstrip("/") + "/"
            if page > 1:
                url = url + f"page/{page}/"
            try:
                resp = await client.get(url)
            except Exception:  # noqa: BLE001
                return
            html = HTMLParser(resp.text)
            cards = html.css("li.product") or html.css(".product")
            if not cards:
                return
            for card in cards:
                listing = _extract_product(card, site_base_url, merchant_slug, category_slug)
                if listing:
                    yield listing
    finally:
        await client.aclose()
