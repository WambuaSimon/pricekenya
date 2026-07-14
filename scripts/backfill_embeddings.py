"""One-shot: compute MiniLM embeddings for every Product with NULL embedding.

Idempotent: only touches rows where embedding IS NULL. Safe to re-run after
adding new products. Batches encode calls so PyTorch stays warm.

Usage:
    python -m scripts.backfill_embeddings
    python -m scripts.backfill_embeddings --category phones
    python -m scripts.backfill_embeddings --batch-size 64 --limit 500
"""

from __future__ import annotations

import argparse
import time

from sqlmodel import Session, select

from db.models import Product
from db.session import engine
from matching import embeddings


def _iter_missing(session: Session, category: str | None, limit: int | None):
    q = select(Product).where(Product.embedding.is_(None))
    if category:
        q = q.where(Product.category_slug == category)
    q = q.order_by(Product.id)
    if limit:
        q = q.limit(limit)
    return session.exec(q).all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", help="Only backfill this category slug (default: all)")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--limit", type=int, help="Cap the total number of rows")
    args = parser.parse_args()

    embeddings.allow_encode()

    with Session(engine) as session:
        rows = _iter_missing(session, args.category, args.limit)
        total = len(rows)
        if total == 0:
            print("no products missing embeddings — noop")
            return

        print(f"embedding {total} products (batch_size={args.batch_size})")
        start = time.perf_counter()
        done = 0
        for i in range(0, total, args.batch_size):
            batch = rows[i : i + args.batch_size]
            texts = [p.title or p.canonical_key or " " for p in batch]
            vecs = embeddings.encode_batch(texts)
            for p, v in zip(batch, vecs, strict=True):
                p.embedding = v
                session.add(p)
            session.commit()
            done += len(batch)
            elapsed = time.perf_counter() - start
            rate = done / elapsed if elapsed > 0 else 0.0
            print(f"  {done}/{total}  ({rate:.1f} rows/s)")

    print("done")


if __name__ == "__main__":
    main()
