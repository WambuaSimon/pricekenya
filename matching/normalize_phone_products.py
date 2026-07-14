"""Retro-canonicalise every Product against the CURRENT per-category matchers.

Fixes two bug classes that historically produced garbage on product pages:

  1. Over-merged model variants. Before the phone _MODEL_RE fix (2026-07-14),
     "iPhone 14 Pro" and "iPhone 14 Pro Max" both extracted model="iphone 14
     pro" and landed under the same Product — buyers saw prices spanning
     ~KSh 60k–205k on one page. Same class of bug can hit any category
     whose matcher gets tightened after data was already ingested.

  2. Accessories mis-categorised as their host category. Screen protectors,
     cases, chargers, and wristbands ingested before their category's
     accessory gate landed sit in the DB as if they were phones/tablets/
     laptops/etc. They have no distinguishing spec and collapse into
     whichever host model their title mentions.

Approach: for every current Listing, re-parse the merchant title with
`match_or_create_product(...)`, using the LISTING's parent-Product
category. Move the listing to a Product with the right canonical_key
(creating one if none exists); if the matcher rejects the title, delete
the listing plus its price-history rows.

After processing, any Product with zero listings is dropped.

Idempotent: running twice against a clean DB does nothing.

Usage:
    python -m matching.normalize_phone_products                # dry-run, all categories
    python -m matching.normalize_phone_products --apply        # mutate, all categories
    python -m matching.normalize_phone_products --category phones --apply
"""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from db.models import Click, Listing, PriceHistory, Product
from db.session import engine
from matching.match import match_or_create_product
from matching.normalize import parse_title


def _drop_listing_dependents(session: Session, listing_id: int) -> None:
    """Delete every row that FK-references Listing(listing_id) and flush
    so Postgres accepts the subsequent DELETE on the listing itself.

    Listing is currently referenced from:
      - pricehistory.listing_id
      - click.listing_id

    New FK columns added in future should also be swept here — otherwise
    the first delete run in the wild throws a ForeignKeyViolation."""
    for ph in session.exec(
        select(PriceHistory).where(PriceHistory.listing_id == listing_id)
    ).all():
        session.delete(ph)
    for c in session.exec(select(Click).where(Click.listing_id == listing_id)).all():
        session.delete(c)
    # Flush so both DELETEs hit the DB before the caller deletes the
    # Listing row itself — the FK constraint is checked per-statement.
    session.flush()


def _scan(category: str | None) -> tuple[list, list, set[int]]:
    """Read-only pass that returns the mutation plan without touching state.

    Uses a single JOIN query so every listing + its host Product's key /
    category ships in one round trip. The old N+1 loop was blowing past
    Neon's SSL idle timeout partway through ~5k products.

    Returns:
        moves    — list of (listing_id, new_key, category_slug, title, old_prod_id)
        deletes  — list of (listing_id, title, category_slug)
        touched  — set of Product.id values that lose ≥1 listing
    """
    moves: list[tuple[int, str, str, str, int]] = []
    deletes: list[tuple[int, str, str]] = []
    touched: set[int] = set()

    stmt = select(
        Listing.id,
        Listing.title_on_merchant,
        Listing.product_id,
        Product.canonical_key,
        Product.category_slug,
    ).join(Product, Product.id == Listing.product_id)
    if category:
        stmt = stmt.where(Product.category_slug == category)

    with Session(engine) as s:
        rows = s.exec(stmt).all()

    for lst_id, title, prod_id, current_key, cat_slug in rows:
        parsed = parse_title(title, category=cat_slug)
        new_key = parsed.canonical_key
        if new_key is None:
            deletes.append((lst_id, title, cat_slug))
            touched.add(prod_id)
        elif new_key != current_key:
            moves.append((lst_id, new_key, cat_slug, title, prod_id))
            touched.add(prod_id)
    return moves, deletes, touched


def _dry_run(category: str | None) -> tuple[int, int, int]:
    """Report what would change without touching the DB."""
    moves, deletes, touched = _scan(category)
    for _lst_id, new_key, cat_slug, title, prod_id in moves:
        print(f"  MOVE    [{cat_slug}] product #{prod_id} → [{new_key}]  {title[:60]!r}")
    for _lst_id, title, cat_slug in deletes:
        print(f"  REJECT  [{cat_slug}]  {title[:60]!r}")
    return len(moves), len(deletes), len(touched)


def _apply(category: str | None) -> tuple[int, int, int]:
    """Mutate the DB. Returns (moved, rejected_deleted, products_deleted).

    Two phases:
      1. `_scan` (read-only, single JOIN query) figures out the plan.
      2. Apply the plan: delete rejected listings first, then reassign
         moved listings via match_or_create_product (which creates the
         target Product if missing), then sweep any Product left empty.

    Splitting the scan from the mutation means we're not holding an open
    result-set cursor while doing hundreds of writes — the failure mode
    Neon was hitting on the old script."""
    moves, deletes, _ = _scan(category)

    moved = 0
    rejected = 0
    deleted = 0

    with Session(engine) as s:
        # Phase 1: delete listings the matcher now rejects (accessories
        # under a phones/tablets/etc. category). PriceHistory has an FK
        # to Listing so drop history rows first.
        for lst_id, _title, _cat in deletes:
            _drop_listing_dependents(s, lst_id)
            lst = s.get(Listing, lst_id)
            if lst:
                s.delete(lst)
                rejected += 1
        s.commit()

        # Phase 2: reassign listings whose canonical_key has shifted.
        # match_or_create_product returns the correct target Product,
        # creating one if the new key doesn't have a home yet.
        for lst_id, _new_key, cat_slug, title, _old_prod_id in moves:
            new_prod = match_or_create_product(
                session=s, title=title, image_url=None, category=cat_slug,
            )
            if new_prod is None:
                # Shouldn't happen — the scan already routed rejects to
                # `deletes` — but stay defensive.
                continue
            lst = s.get(Listing, lst_id)
            if lst and lst.product_id != new_prod.id:
                lst.product_id = new_prod.id
                s.add(lst)
                moved += 1
        s.commit()

        # Phase 3: dedupe (product_id, merchant_id) pairs. Moving listings
        # from Product A to Product B can leave two listings from the same
        # merchant on Product B if the merchant was already there. Also
        # catches pre-existing duplicates from scrapers that visited the
        # same product URL via two category sub-URLs. Keep the freshest,
        # delete the rest.
        from collections import defaultdict

        by_pair: dict[tuple[int, int], list] = defaultdict(list)
        for lst in s.exec(select(Listing)).all():
            by_pair[(lst.product_id, lst.merchant_id)].append(lst)
        deduped = 0
        for _pair, ls in by_pair.items():
            if len(ls) < 2:
                continue
            ls.sort(key=lambda x: x.last_checked_at, reverse=True)
            for extra in ls[1:]:
                _drop_listing_dependents(s, extra.id)
                s.delete(extra)
                deduped += 1
        if deduped:
            s.commit()
            print(f"  DEDUP  removed {deduped} duplicate (product, merchant) rows")

        # Phase 4: sweep Products with zero listings. Scope by the same
        # category filter so we don't collide with rows a co-running
        # scraper is still populating.
        empty_stmt = (
            select(Product)
            .where(~Product.id.in_(select(Listing.product_id).distinct()))
        )
        if category:
            empty_stmt = empty_stmt.where(Product.category_slug == category)
        for p in s.exec(empty_stmt).all():
            s.delete(p)
            deleted += 1
        s.commit()

    return moved, rejected, deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retro-canonicalise Products against the current per-category matchers."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually mutate the DB. Default is dry-run.",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Restrict to a single category_slug (e.g. phones, laptops). "
        "Default: run across every category with any Products.",
    )
    args = parser.parse_args()
    scope = args.category or "all categories"

    if args.apply:
        moved, rejected, deleted = _apply(args.category)
        print(
            f"\nDone ({scope}).  moved={moved}  rejected(deleted)={rejected}  "
            f"products_deleted={deleted}"
        )
    else:
        moved, rejected, potentially_emptied = _dry_run(args.category)
        print(
            f"\nDry-run ({scope}).  would_move={moved}  would_reject={rejected}  "
            f"products_potentially_emptied={potentially_emptied}"
        )
        print("Re-run with --apply to mutate.")


if __name__ == "__main__":
    main()
