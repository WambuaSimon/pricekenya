"""One-shot: for products with no image_url, fetch og:image from each
merchant product-detail page and use the first real one.

Rationale: many merchants (Avechi, Zurimall, techonline, etc.) lazy-load
their card-thumbnails with a placeholder GIF, so the scraper's card-level
image extraction sees only the placeholder. But every merchant product-
detail page ships a proper `<meta property="og:image">` — that's what
Facebook/WhatsApp shows in previews. This script uses that as fallback.

Order: iterates a product's listings by last_checked_at desc so the
freshest merchant page gets tried first. Skips known placeholder URLs and
retries the next listing.

Idempotent: only touches products where image_url IS NULL. Safe to re-run.

Usage:
    python -m scripts.fetch_missing_images --dry-run          # preview
    python -m scripts.fetch_missing_images                    # apply
    python -m scripts.fetch_missing_images --category cameras # limit
    python -m scripts.fetch_missing_images --limit 200        # cap work
"""

from __future__ import annotations

import argparse
import asyncio
import time
from urllib.parse import urljoin

from selectolax.parser import HTMLParser
from sqlmodel import Session, select

from db.models import Listing, Product
from db.session import engine
from scrapers.common.base import CffiPoliteClient, PoliteClient
from scrapers.common.woocommerce import is_placeholder_image

# Merchants that fingerprint TLS (Cloudflare/Akamai). For these, use
# curl_cffi's Chrome impersonation instead of vanilla httpx.
_CFFI_MERCHANT_HOSTS = (
    "naivas.online",
    "phoneplacekenya.com",
    "carrefour.ke",
    "quickmart.co.ke",
)


def _needs_cffi(url: str) -> bool:
    lower = url.lower()
    return any(host in lower for host in _CFFI_MERCHANT_HOSTS)


_META_OG_PROPS = (
    ("property", "og:image:secure_url"),
    ("property", "og:image"),
    ("name", "og:image"),
    ("name", "twitter:image"),
    ("property", "twitter:image"),
)


def _og_image_from(html: str, base_url: str) -> str | None:
    """Extract the first real og:image URL from a merchant product page."""
    dom = HTMLParser(html)
    for attr, val in _META_OG_PROPS:
        for node in dom.css(f'meta[{attr}="{val}"]'):
            content = (node.attributes.get("content") or "").strip()
            if not content or is_placeholder_image(content):
                continue
            # Some CMSes emit relative URLs. Resolve against the page.
            if content.startswith("//"):
                content = "https:" + content
            elif content.startswith("/"):
                content = urljoin(base_url, content)
            if not content.startswith(("http://", "https://")):
                continue
            return content
    return None


async def _try_one_listing(url: str) -> str | None:
    """Fetch a merchant product page, return first real og:image URL or None."""
    client = CffiPoliteClient() if _needs_cffi(url) else PoliteClient()
    try:
        try:
            resp = await client.get(url)
        except Exception:  # noqa: BLE001 — merchant returned 4xx/5xx/timeout
            return None
        # curl_cffi returns .text; httpx has .text
        text = getattr(resp, "text", None)
        if not text:
            return None
        return _og_image_from(text, url)
    finally:
        await client.aclose()


async def _fetch_for_product(product: Product, listings: list[Listing]) -> str | None:
    # Try each listing URL; first real og:image wins.
    for listing in listings:
        found = await _try_one_listing(listing.url)
        if found:
            return found
    return None


async def _run(session: Session, categories: set[str] | None, limit: int | None, dry: bool) -> None:
    q = select(Product).where(Product.image_url.is_(None))
    if categories:
        q = q.where(Product.category_slug.in_(list(categories)))
    q = q.order_by(Product.id)
    if limit:
        q = q.limit(limit)
    products = session.exec(q).all()

    print(f"products missing image_url: {len(products)}")
    if not products:
        return

    filled = 0
    skipped = 0
    start = time.perf_counter()
    for i, product in enumerate(products, 1):
        listings = session.exec(
            select(Listing)
            .where(Listing.product_id == product.id)
            .order_by(Listing.last_checked_at.desc())
        ).all()
        if not listings:
            skipped += 1
            continue

        found = await _fetch_for_product(product, listings)
        if not found:
            skipped += 1
        else:
            filled += 1
            if not dry:
                product.image_url = found
                session.add(product)
                # Commit every 10 rows so a mid-run interrupt keeps progress.
                if filled % 10 == 0:
                    session.commit()

        if i % 25 == 0 or i == len(products):
            rate = i / (time.perf_counter() - start)
            print(
                f"  {i}/{len(products)}  filled={filled}  skipped={skipped}  "
                f"({rate:.1f} products/s)"
            )

    if not dry:
        session.commit()
    print()
    print(f"done — filled {filled}, skipped {skipped}")
    if dry:
        print("(--dry-run — no writes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--category", action="append", help="Limit to category slug(s)")
    parser.add_argument("--limit", type=int, help="Cap products processed")
    args = parser.parse_args()

    categories = set(args.category) if args.category else None
    with Session(engine) as session:
        asyncio.run(_run(session, categories, args.limit, args.dry_run))


if __name__ == "__main__":
    main()
