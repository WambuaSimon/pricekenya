"""One-shot: for products with no usable image_url, fetch og:image from each
merchant product-detail page and use the first real one.

Rationale: many merchants (Avechi, Zurimall, techonline, etc.) lazy-load
their card-thumbnails with a placeholder GIF, so the scraper's card-level
image extraction sees only the placeholder. But every merchant product-
detail page ships a proper `<meta property="og:image">` — that's what
Facebook/WhatsApp shows in previews. This script uses that as fallback.

Order: iterates a product's listings by last_checked_at desc so the
freshest merchant page gets tried first. Skips known placeholder URLs and
retries the next listing.

Two target sets, because "no image" and "an image that never loads" look
identical to a shopper (both render the brand-name fallback tile):

  default           products where image_url IS NULL
  --repair-broken   *also* products whose image_url sits on a host from
                    scrapers/common/image_hosts.BLOCKED_IMAGE_HOSTS — hosts
                    measured to 403/404 every hotlinked request. Those rows
                    are not missing data, they are wrong data, and until
                    2026-10-26 nothing could ever overwrite them.

In both modes a merchant on a blocked host is skipped when hunting for the
replacement, so the repair cannot hand back a URL as dead as the one it
replaces.

Idempotent in both modes: a product only leaves the target set once it holds
an image that is neither NULL nor blocked. Safe to re-run.

Usage:
    python -m scripts.fetch_missing_images --dry-run            # preview
    python -m scripts.fetch_missing_images                      # apply
    python -m scripts.fetch_missing_images --repair-broken      # + dead hosts
    python -m scripts.fetch_missing_images --category cameras   # limit
    python -m scripts.fetch_missing_images --limit 200          # cap work
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
from scrapers.common.image_hosts import is_blocked_image_host
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
    """First real og:image across this product's listings, or None.

    Merchants on a blocked host are skipped outright. Their detail pages
    serve og:image URLs on that same domain, so fetching them can only
    produce a replacement that fails exactly like the one we are trying to
    replace — and for the 403 hosts the page fetch itself tends to fail
    anyway. The found URL is re-checked for the same reason: a merchant may
    host its own pages fine while pointing og:image at a blocked CDN.
    """
    for listing in listings:
        if is_blocked_image_host(listing.url):
            continue
        found = await _try_one_listing(listing.url)
        if found and not is_blocked_image_host(found):
            return found
    return None


async def _run(
    session: Session,
    categories: set[str] | None,
    limit: int | None,
    dry: bool,
    repair_broken: bool,
) -> None:
    q = select(Product)
    if categories:
        q = q.where(Product.category_slug.in_(list(categories)))
    # Ordering by offer count would be the ideal work order — those products
    # are both the worst affected and the most visited — but it needs a join
    # and a GROUP BY for a script that is expected to run to completion
    # anyway. Product.id keeps --limit runs resumable instead.
    q = q.order_by(Product.id)

    if repair_broken:
        # The blocked-host test lives in Python, not SQL, so filter after
        # the fetch. `--limit` then has to be applied here too, otherwise it
        # would cap the rows *scanned* rather than the rows *worked on* and
        # a small --limit would usually find nothing to do.
        candidates = [
            p
            for p in session.exec(q).all()
            if p.image_url is None or is_blocked_image_host(p.image_url)
        ]
        products = candidates[:limit] if limit else candidates
        missing = sum(1 for p in products if p.image_url is None)
        print(
            f"products to repair: {len(products)} "
            f"({missing} missing, {len(products) - missing} on a blocked host)"
        )
    else:
        q = q.where(Product.image_url.is_(None))
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
            # Printed on real runs as well as previews, not just because a
            # preview that only prints a count can't be checked, but because
            # on a real run this is the only record of the URL being
            # overwritten. Tee it to a file and it's the undo script.
            print(f"    {product.slug}\n      - {product.image_url}\n      + {found}")
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
    parser.add_argument(
        "--repair-broken",
        action="store_true",
        help="Also re-fetch products whose image_url is on a blocked host",
    )
    args = parser.parse_args()

    categories = set(args.category) if args.category else None
    with Session(engine) as session:
        asyncio.run(
            _run(session, categories, args.limit, args.dry_run, args.repair_broken)
        )


if __name__ == "__main__":
    main()
