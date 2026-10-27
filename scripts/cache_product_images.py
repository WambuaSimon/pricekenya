"""Backfill: copy every product's merchant image into our own R2 bucket.

Turns the site's images from hotlinks into our own copies. See
scrapers/common/image_cache.py for why that matters and OPERATIONS.md 8ag
for the outage that motivated it.

Writes `product.image_cached_url` and never touches `image_url`, so the
original stays as provenance, the cache is rebuildable from scratch, and a
miss falls back to today's behaviour.

Idempotent: rows that already have a cached URL are skipped, and the object
key is the content hash, so a re-run uploads nothing new.

Usage:
    python -m scripts.cache_product_images --dry-run
    python -m scripts.cache_product_images --category phones
    python -m scripts.cache_product_images --limit 500
    python -m scripts.cache_product_images --recache     # redo cached rows
"""

from __future__ import annotations

import argparse
import asyncio
import time

import httpx
from sqlmodel import Session, select

from db.models import Product
from db.session import engine
from scrapers.common.image_cache import cache_enabled, cache_image, preflight

# Merchant servers, not a CDN we own. Keep the concurrency low enough that a
# backfill never looks like an attack to a small Kenyan shop — the whole
# point is to stop depending on their goodwill, not to burn it on the way out.
CONCURRENCY = 6


async def _one(product_id: int, url: str, client, sem) -> tuple[int, str | None]:
    async with sem:
        return product_id, await cache_image(url, client=client)


async def _run(session: Session, categories, limit, dry, recache) -> None:
    if not cache_enabled():
        print(
            "R2 is not configured — set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
            "R2_SECRET_ACCESS_KEY, R2_BUCKET (and R2_PUBLIC_BASE_URL).\n"
            "Nothing to do; the site keeps hotlinking."
        )
        return

    q = select(Product).where(Product.image_url.is_not(None))
    if not recache:
        q = q.where(Product.image_cached_url.is_(None))
    if categories:
        q = q.where(Product.category_slug.in_(list(categories)))
    q = q.order_by(Product.id)
    if limit:
        q = q.limit(limit)
    products = session.exec(q).all()
    print(f"products to cache: {len(products)}")
    if not products or dry:
        if dry:
            for p in products[:20]:
                print(f"  would cache {p.slug}: {p.image_url}")
            print("(--dry-run — no fetches, no writes)")
        return

    # Prove a written URL is actually fetchable BEFORE touching a live table.
    # image_cached_url is preferred over image_url by the templates, so a URL
    # that does not serve replaces a working merchant image with a broken one
    # — the fallback covers NULL, not broken.
    async with httpx.AsyncClient() as probe_client:
        problem = await preflight(client=probe_client)
    if problem:
        print(f"preflight failed: {problem}")
        print("refusing to write image_cached_url until a stored object is fetchable.")
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    cached = failed = 0
    start = time.perf_counter()
    async with httpx.AsyncClient(
        headers={
            # Identify ourselves honestly. These are the same merchants the
            # scraper already talks to; a backfill should not hide.
            "User-Agent": "PriceKenyaBot/0.1 (+https://pricekenya.co.ke)",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
        },
    ) as client:
        tasks = [_one(p.id, p.image_url, client, sem) for p in products]
        by_id = {p.id: p for p in products}
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            pid, url = await coro
            if url:
                by_id[pid].image_cached_url = url
                session.add(by_id[pid])
                cached += 1
                if cached % 25 == 0:
                    session.commit()
            else:
                failed += 1
            if i % 100 == 0 or i == len(tasks):
                rate = i / (time.perf_counter() - start)
                print(f"  {i}/{len(tasks)}  cached={cached} failed={failed} ({rate:.1f}/s)")
    session.commit()
    print(f"\ndone — cached {cached}, failed {failed}")
    if failed:
        print("failures are expected for the blocked hosts; they keep hotlinking.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--category", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--recache", action="store_true", help="Redo already-cached rows")
    args = parser.parse_args()
    with Session(engine) as session:
        asyncio.run(
            _run(session, set(args.category) if args.category else None,
                 args.limit, args.dry_run, args.recache)
        )


if __name__ == "__main__":
    main()
