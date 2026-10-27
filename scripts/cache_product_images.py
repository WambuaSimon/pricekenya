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


# Rows per DB write. The point is that the session is open for milliseconds
# at a time, not for the whole run: the first full backfill held one Session
# across an hour of slow HTTP and Postgres eventually closed the connection
# underneath it ("server closed the connection unexpectedly"), losing the run
# at 1,800 of 9,806. Fetch with no session held, then write in a short burst.
BATCH = 50


async def _one(product_id: int, url: str, client, sem, stats) -> tuple[int, str | None]:
    async with sem:
        return product_id, await cache_image(url, client=client, stats=stats)


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


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

    # Snapshot the work as plain tuples and let the caller's session go. From
    # here on no DB connection is held while we are doing network I/O.
    work = [(p.id, p.image_url) for p in products]

    sem = asyncio.Semaphore(CONCURRENCY)
    cached = failed = done = 0
    stats: dict[str, int] = {}
    start = time.perf_counter()
    async with httpx.AsyncClient(
        headers={
            # Identify ourselves honestly. These are the same merchants the
            # scraper already talks to; a backfill should not hide.
            "User-Agent": "PriceKenyaBot/0.1 (+https://pricekenya.co.ke)",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
        },
    ) as client:
        for batch in _chunks(work, BATCH):
            results = await asyncio.gather(
                *(_one(pid, url, client, sem, stats) for pid, url in batch)
            )
            got = [(pid, url) for pid, url in results if url]
            failed += len(results) - len(got)
            done += len(results)

            # Short-lived session per batch. A dropped connection now costs
            # one batch, and the next batch simply opens a new one.
            if got:
                with Session(engine) as write:
                    for pid, url in got:
                        product = write.get(Product, pid)
                        if product is not None:
                            product.image_cached_url = url
                            write.add(product)
                    write.commit()
                cached += len(got)

            rate = done / (time.perf_counter() - start)
            print(f"  {done}/{len(work)}  cached={cached} failed={failed} ({rate:.1f}/s)", flush=True)

    print(f"\ndone — cached {cached}, failed {failed}")
    if stats:
        print("failure reasons:")
        for reason, n in sorted(stats.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>5}  {reason}")
        print("http:403/404 on the known blocked hosts is expected — they keep hotlinking.")


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
