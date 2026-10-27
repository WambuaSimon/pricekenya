"""Propose manufacturer images for products that have no usable one.

Writes ProductImageCandidate rows for review at /admin/image-review. Nothing
is published: see db/models.ProductImageCandidate for why a human gate is
non-negotiable here.

Targets products where neither a cached copy nor a working merchant image
exists — i.e. image_url IS NULL, or it sits on a host we know blocks us.

Idempotent: a (product, source) pair is unique, so re-running tops the queue
up rather than duplicating it.

Usage:
    python -m scripts.propose_product_images --dry-run
    python -m scripts.propose_product_images --category phones
    python -m scripts.propose_product_images --limit 50
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import Product, ProductImageCandidate
from db.session import engine
from scrapers.common.image_hosts import is_blocked_image_host
from scrapers.common.image_sources import propose

# Manufacturer sites, hit a handful of times. Stay polite and serial-ish.
CONCURRENCY = 3


def _needs_image(p: Product) -> bool:
    if p.image_cached_url:
        return False
    return p.image_url is None or is_blocked_image_host(p.image_url)


async def _run(session: Session, categories, limit, dry) -> None:
    q = select(Product)
    if categories:
        q = q.where(Product.category_slug.in_(list(categories)))
    targets = [p for p in session.exec(q.order_by(Product.id)).all() if _needs_image(p)]

    already = {
        (c.product_id, c.source)
        for c in session.exec(select(ProductImageCandidate)).all()
    }
    targets = [p for p in targets if (p.id, (p.brand or "").lower()) not in already]
    if limit:
        targets = targets[:limit]

    print(f"products with no usable image and no open proposal: {len(targets)}")
    if not targets:
        return
    if dry:
        for p in targets[:25]:
            print(f"  would query {p.brand}: {p.title}")
        print("(--dry-run — no network, no writes)")
        return

    sem = asyncio.Semaphore(CONCURRENCY)
    proposed = skipped = 0

    async def _one(p: Product, client):
        async with sem:
            return p, await propose(p.brand or "", p.title, client=client)

    async with httpx.AsyncClient() as client:
        for coro in asyncio.as_completed([_one(p, client) for p in targets]):
            product, cand = await coro
            if not cand:
                skipped += 1
                continue
            row = ProductImageCandidate(
                product_id=product.id,
                image_url=cand.image_url,
                source_url=cand.source_url,
                source=cand.source,
                matched_title=product.title,
            )
            session.add(row)
            try:
                session.commit()
                proposed += 1
                print(f"  proposed {product.slug} <- {cand.source}: {cand.image_url[:90]}")
            except IntegrityError:
                # Raced with another run on the same (product, source).
                session.rollback()
                skipped += 1

    print(f"\ndone — {proposed} proposed, {skipped} with no manufacturer hit")
    if proposed:
        print("review them at /admin/image-review — nothing is live until approved.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--category", action="append")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    with Session(engine) as session:
        asyncio.run(_run(session, set(args.category) if args.category else None,
                         args.limit, args.dry_run))


if __name__ == "__main__":
    main()
