"""One-shot: mark obviously-different merge candidates as rejected.

Any ProductMergeCandidate still `pending` where the two products have
conflicting numeric specs (55" vs 65", 128GB vs 256GB) or clearly
different model codes (MK220 vs MK270) is a MiniLM false positive —
reviewer attention shouldn't be wasted on them.

Idempotent. Prints one line per pruned candidate + a summary at the end.

Usage:
    python -m scripts.prune_merge_candidates                 # actually prune
    python -m scripts.prune_merge_candidates --dry-run       # just report
"""

from __future__ import annotations

import argparse
from datetime import datetime

from sqlmodel import Session, select

from db.models import Product, ProductMergeCandidate
from db.session import engine
from matching.match import _obviously_different_products


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't write")
    args = parser.parse_args()

    with Session(engine) as session:
        pending = session.exec(
            select(ProductMergeCandidate).where(
                ProductMergeCandidate.status == "pending"
            )
        ).all()

        pruned = 0
        kept = 0
        for cand in pending:
            source = session.get(Product, cand.source_product_id)
            target = session.get(Product, cand.target_product_id)
            if not (source and target):
                continue
            if _obviously_different_products(
                source.specs, source.canonical_key,
                target.specs, target.canonical_key,
            ):
                pruned += 1
                print(
                    f"  prune  sim={cand.similarity:.3f}  "
                    f"{source.canonical_key}  <->  {target.canonical_key}"
                )
                if not args.dry_run:
                    cand.status = "rejected"
                    cand.reviewed_at = datetime.utcnow()
                    cand.reviewer_note = "auto-pruned: obvious spec/model conflict"
                    session.add(cand)
            else:
                kept += 1

        if not args.dry_run:
            session.commit()

        print()
        print(f"pending candidates: {len(pending)}")
        print(f"  pruned (rejected): {pruned}")
        print(f"  kept for review:   {kept}")
        if args.dry_run:
            print("  (--dry-run — no writes)")


if __name__ == "__main__":
    main()
