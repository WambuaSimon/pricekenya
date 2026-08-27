"""One-shot backfill: re-home washer listings after the combo-capacity fix.

Companion to the `matching/washer.py` change that stopped reading combo
capacity specs backwards. That fix corrects future scrapes; this moves the
rows already on record.

## What went wrong

`_CAPACITY_RE` scanned "15/8 Kg", found no "kg" after 15, matched "8 Kg" and
returned the DRY capacity as the machine's capacity. Separately, the dryer
marker list missed "washer and dryer", so those listings also lost their
`with-dryer` segment. Together, "LG 15/8 Kg Front Load Washer and Dryer"
produced `lg|8kg|front` — identical to the genuine "LG 8KG Front Load
Washing Machine", merging a 238,995 combo into a 62,995 washer.

Measured on prod 2026-08-27: all 54 combo listings were keyed on their
dryer figure, and 57 canonical keys change under the fix.

## What this does

Re-runs `match_or_create_product` over every listing in the category, using
the same code path ingest uses, and repoints each listing at whatever
product that returns. Nothing here re-implements matching: the point is to
land exactly where the next scrape would, only sooner.

Three outcomes per existing product, all observed on prod:

  - untouched (232) — every listing still keys to it
  - split (9) — it keeps its genuine listings and sheds mis-parsed combos,
    e.g. `hisense|8kg|front` keeps 7 of 9
  - emptied (26) — it was built entirely from mis-parsed combos, so every
    listing leaves

## Emptied products get a redirect, not a bare delete

Those 26 are URLs Google has probably indexed. `db.redirects.record_redirect`
writes a ProductRedirect so `product_detail` serves a 301 to the product that
took most of the orphan's listings, instead of a permanent 404. That rule —
no code path deletes a Product without recording where its slug went — is
the one `db/redirects.py` exists to enforce.

Same-merchant duplicates are collapsed when two listings land on one product,
keeping the freshest, so `Where to buy` cannot show a shop twice.

Usage:
    python -m scripts.rematch_washer_dryers                  # dry run
    python -m scripts.rematch_washer_dryers --apply          # actually move
    python -m scripts.rematch_washer_dryers --category tvs   # other category

Idempotent: a second run after a successful one is a no-op, because every
listing already sits on the product its title resolves to.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from sqlmodel import Session, delete, select

from db.models import Click, Listing, PriceHistory, Product
from db.redirects import record_redirect
from db.session import engine
from matching.match import match_or_create_product

DEFAULT_CATEGORY = "washers-dryers"


def _drop_listing(session: Session, listing_id: int) -> None:
    """Remove a listing and everything pointing at it.

    Both child FKs are NOT NULL, so the children have to go first or
    Postgres refuses the delete and rolls back the whole transaction.
    """
    session.exec(delete(PriceHistory).where(PriceHistory.listing_id == listing_id))
    session.exec(delete(Click).where(Click.listing_id == listing_id))
    session.exec(delete(Listing).where(Listing.id == listing_id))


def run(*, category: str = DEFAULT_CATEGORY, apply: bool = False) -> int:
    """Re-home listings in `category`. Returns the number of moves needed."""
    with Session(engine) as session:
        rows = session.exec(
            select(Listing, Product)
            .join(Product, Product.id == Listing.product_id)
            .where(Product.category_slug == category)
        ).all()
        if not rows:
            print(f"No listings in category {category!r}.")
            return 0

        # Where each listing should live, according to the current matcher.
        moves: list[tuple[Listing, Product, Product]] = []
        unmatchable = 0
        for listing, old_product in rows:
            target = match_or_create_product(
                session,
                title=listing.title_on_merchant,
                image_url=listing.product.image_url if listing.product else None,
                category=category,
            )
            if target is None:
                # Title no longer parses. Leave it where it is rather than
                # stranding it — a listing with no product is invisible and
                # unrecoverable without a re-scrape.
                unmatchable += 1
                continue
            if target.id != old_product.id:
                moves.append((listing, old_product, target))

        print(f"category {category!r}: {len(rows)} listing(s)")
        print(f"  already correct : {len(rows) - len(moves) - unmatchable}")
        print(f"  need moving     : {len(moves)}")
        if unmatchable:
            print(f"  unparseable     : {unmatchable} (left in place)")

        if moves:
            print("\n  moves:")
            shown = set()
            for listing, old, new in moves:
                pair = (old.canonical_key, new.canonical_key)
                if pair in shown:
                    continue
                shown.add(pair)
                print(f"    {old.canonical_key:<30} -> {new.canonical_key:<32} {listing.title_on_merchant[:34]}")

        if not apply:
            session.rollback()  # match_or_create_product may have created rows
            print("\nDry run. Re-run with --apply to move these listings.")
            return len(moves)

        # Repoint, collapsing same-merchant duplicates on the way.
        seen_on_target: dict[tuple[int, int], Listing] = {}
        for listing, _old, target in moves:
            slot = (target.id, listing.merchant_id)
            existing = seen_on_target.get(slot) or session.exec(
                select(Listing)
                .where(Listing.product_id == target.id)
                .where(Listing.merchant_id == listing.merchant_id)
            ).first()
            if existing is not None and existing.id != listing.id:
                loser, winner = (
                    (listing, existing)
                    if (existing.last_checked_at or 0) >= (listing.last_checked_at or 0)
                    else (existing, listing)
                )
                _drop_listing(session, loser.id)
                seen_on_target[slot] = winner
                if loser.id == listing.id:
                    continue
            listing.product_id = target.id
            session.add(listing)
            seen_on_target[slot] = listing
        session.flush()

        # Anything left with no listings is a URL that must not become a 404.
        emptied = session.exec(
            select(Product)
            .outerjoin(Listing, Listing.product_id == Product.id)
            .where(Product.category_slug == category)
            .where(Listing.id.is_(None))
        ).all()
        destinations: dict[int, Counter] = defaultdict(Counter)
        for _listing, old, new in moves:
            destinations[old.id][new.slug] += 1

        redirected = 0
        for product in emptied:
            targets = destinations.get(product.id)
            if not targets:
                # Emptied by something other than this run; leave it alone
                # rather than guessing a destination for its slug.
                continue
            new_slug = targets.most_common(1)[0][0]
            record_redirect(session, old_slug=product.slug, new_slug=new_slug)
            session.delete(product)
            redirected += 1

        session.commit()
        print(f"\nMoved {len(moves)} listing(s).")
        print(f"Deleted {redirected} emptied product(s), each with a 301 redirect recorded.")
        return len(moves)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-home listings onto correctly-keyed products.")
    parser.add_argument("--category", default=DEFAULT_CATEGORY)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually move rows. Without this the script only reports.",
    )
    args = parser.parse_args(argv)
    run(category=args.category, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
