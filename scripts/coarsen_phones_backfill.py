"""One-shot backfill: consolidate phone Products split by storage/RAM tiers.

Context — see CONTEXT.md §8h and the phones-category audit on 2026-08-05.
The regex parser + compose_keys previously produced canonical_keys like
`samsung|s25|128|8`, splitting one phone across 2-9 separate Product rows
by storage/RAM tier. Every merchant's title format is slightly different,
so cross-merchant matches were failing and 73% of phone products had a
single listing.

Sibling code change (matching/phone.py + matching/compose_keys.py) drops
storage+RAM from the canonical_key going forward. This script updates
EXISTING Product rows to the coarsened key and merges duplicates that
now collide, reparenting listings from loser rows to a chosen winner.

Safety:
- Only touches products in `--category phones` (default). Can be pointed
  at other categories later once their composers are similarly coarsened.
- Winner selection: highest listing count, ties broken by earliest
  created_at. Deterministic; a re-run picks the same winner.
- Handles Listing UNIQUE(product_id, merchant_id) collisions by dropping
  the loser's duplicate merchant listing (keeping the winner's).
- --dry-run prints the merge plan without touching the DB.
- Non-phone products untouched.

Run:
    python -m scripts.coarsen_phones_backfill --dry-run
    python -m scripts.coarsen_phones_backfill  # actually merges

Idempotent — re-running on the same DB after a successful merge is a no-op.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

from sqlalchemy import delete, update
from sqlmodel import Session, func, select

from db.models import Listing, PriceHistory, Product
from db.session import engine
from matching.base import slugify

logger = logging.getLogger(__name__)


def _new_key(product: Product) -> str | None:
    """Recompute the coarsened canonical_key for a product.

    Matches the format produced by the new regex parser + composer
    (matching/phone.py, matching/compose_keys.py:compose_phones after
    the 2026-08-05 coarsening).
    """
    if not (product.brand and product.model):
        return None
    return f"{slugify(product.brand)}|{slugify(product.model)}"


def _select_winner(products: list[Product], listing_counts: dict[int, int]) -> Product:
    """Highest listing count wins; ties → earliest created_at.

    Deterministic so a re-run picks the same winner.
    """
    def sort_key(p: Product) -> tuple:
        return (
            -listing_counts.get(p.id, 0),  # negate for DESC
            p.created_at if p.created_at else 0,
            p.id,  # final tiebreak — never mixes across sessions
        )
    return sorted(products, key=sort_key)[0]


def _merge_group(
    session: Session, winner: Product, losers: list[Product], dry_run: bool
) -> tuple[int, int]:
    """Reparent listings from losers → winner, dedupe merchant collisions,
    delete loser Products. Returns (reparented_count, dropped_dup_count)."""
    winner_merchants = {
        row[0] for row in session.exec(
            select(Listing.merchant_id).where(Listing.product_id == winner.id)
        ).all()
    }
    reparented = 0
    dropped_dups = 0

    for loser in losers:
        loser_listings = session.exec(
            select(Listing).where(Listing.product_id == loser.id)
        ).all()
        for lst in loser_listings:
            if lst.merchant_id in winner_merchants:
                # Winner already has this merchant's listing — drop the
                # loser's dup to avoid UNIQUE(product_id, merchant_id)
                # constraint violation. Its PriceHistory rows are dropped
                # too (they're keyed to a now-deleted listing).
                if not dry_run:
                    session.execute(
                        delete(PriceHistory).where(PriceHistory.listing_id == lst.id)
                    )
                    session.execute(
                        delete(Listing).where(Listing.id == lst.id)
                    )
                dropped_dups += 1
            else:
                if not dry_run:
                    session.execute(
                        update(Listing)
                        .where(Listing.id == lst.id)
                        .values(product_id=winner.id)
                    )
                winner_merchants.add(lst.merchant_id)
                reparented += 1
        if not dry_run:
            session.execute(delete(Product).where(Product.id == loser.id))

    if not dry_run:
        # Update winner's canonical_key to the new coarsened form.
        new_key = _new_key(winner)
        if new_key and winner.canonical_key != new_key:
            session.execute(
                update(Product)
                .where(Product.id == winner.id)
                .values(canonical_key=new_key)
            )
        session.commit()
    else:
        session.rollback()

    return reparented, dropped_dups


def run(*, category: str, dry_run: bool) -> int:
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(Product.category_slug == category)
        ).all()
        if not products:
            print(f"no products found in category {category!r}")
            return 0

        # Group products by their NEW (coarsened) key.
        groups: dict[str, list[Product]] = defaultdict(list)
        skipped_no_key = 0
        for p in products:
            new_key = _new_key(p)
            if new_key is None:
                skipped_no_key += 1
                continue
            groups[new_key].append(p)

        # Precompute listing counts for winner selection.
        listing_count_rows = session.exec(
            select(Listing.product_id, func.count(Listing.id))
            .join(Product, Product.id == Listing.product_id)
            .where(Product.category_slug == category)
            .group_by(Listing.product_id)
        ).all()
        listing_counts = dict(listing_count_rows)

        merge_groups = [g for g in groups.values() if len(g) > 1]
        singletons = [g for g in groups.values() if len(g) == 1]
        key_updates_needed = sum(
            1 for grp in singletons
            for p in grp
            if p.canonical_key != _new_key(p)
        )

        print("=== phones canonical-key coarsening plan ===")
        print(f"  products in category:            {len(products)}")
        print(f"  skipped (no brand/model):        {skipped_no_key}")
        print(f"  distinct coarsened keys:         {len(groups)}")
        print(f"  groups requiring merge (>1 row): {len(merge_groups)}")
        print(f"  singletons needing key rewrite:  {key_updates_needed}")
        print()
        if dry_run:
            print("=== DRY RUN — showing first 10 merges (no DB writes) ===")
            for grp in merge_groups[:10]:
                winner = _select_winner(grp, listing_counts)
                loser_summary = ", ".join(
                    f"[{p.id}] {p.canonical_key} ({listing_counts.get(p.id, 0)}L)"
                    for p in grp if p.id != winner.id
                )
                print(
                    f"  {_new_key(winner)}: winner=[{winner.id}] "
                    f"{winner.canonical_key} ({listing_counts.get(winner.id, 0)}L), "
                    f"losers={loser_summary}"
                )

        total_reparented = 0
        total_dropped = 0
        merged_groups = 0
        for grp in merge_groups:
            winner = _select_winner(grp, listing_counts)
            losers = [p for p in grp if p.id != winner.id]
            reparented, dropped = _merge_group(session, winner, losers, dry_run)
            total_reparented += reparented
            total_dropped += dropped
            merged_groups += 1

        # Handle singletons that just need their canonical_key rewritten
        # (no merge, just a coarser slug).
        singleton_rewrites = 0
        if not dry_run:
            for grp in singletons:
                p = grp[0]
                new_key = _new_key(p)
                if new_key and p.canonical_key != new_key:
                    session.execute(
                        update(Product)
                        .where(Product.id == p.id)
                        .values(canonical_key=new_key)
                    )
                    singleton_rewrites += 1
            session.commit()

        print()
        print(f"=== result ({'DRY RUN' if dry_run else 'APPLIED'}) ===")
        print(f"  groups merged:              {merged_groups}")
        print(f"  listings reparented:        {total_reparented}")
        print(f"  duplicate listings dropped: {total_dropped}")
        if not dry_run:
            print(f"  singleton key rewrites:     {singleton_rewrites}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--category", default="phones", help="Category slug (default: phones)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without touching DB")
    args = parser.parse_args(argv)
    return run(category=args.category, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
