"""Delete stored listings whose price is too large to be real.

Companion to the guard in `scrapers/ingest.py`. That guard stops new rows
arriving; this clears the ones already on record, which the guard cannot
retroactively reject.

## Why these rows exist

smartdevices-ke publishes prices inflated by ~1e6 on some products. Their
own category HTML carries, verbatim:

    <bdi><span class="woocommerce-Price-currencySymbol">KSh</span>86,000,000,000.00</bdi>

KSh 86 billion for a washing machine (86,000 x 1e6). The scraper parsed it
correctly and ingest stored it. Measured on prod 2026-08-27: 10 such rows,
and they were the only listings above KSh 10m in the whole catalog.

## Why they matter

Every price-spread figure on the site derives from `max(price)` across a
product's live listings: the homepage "Where the gap is biggest" cards, the
product page's "Dearest" panel and spread sentence, and the category grid's
"Save up to" line. One of these rows rewrites all three for its product.

The display layer in `app/pricing.py` already refuses to publish a savings
claim it cannot believe, so nothing false is user-visible today. But that is
a guard, not a fix: the bad rows still sit in `Where to buy`, still skew the
`AggregateOffer` highPrice in the product page's JSON-LD, and still count
toward offer totals. Deleting them is the actual repair.

## Deletion, not correction

The rows are dropped rather than divided by 1e6. The inflation factor is
inferred from a handful of samples, not documented by the merchant, and a
silently "corrected" price that turns out wrong is worse than an absent one
on a site whose entire proposition is accurate prices. The next scrape
re-adds the product at whatever the merchant then publishes, and the ingest
guard keeps it out if that is still garbage.

PriceHistory rows referencing a deleted Listing are removed too, so the
weekly chart on the product page cannot resurrect the bad figure.

Usage:
    python -m scripts.purge_implausible_prices               # dry run
    python -m scripts.purge_implausible_prices --apply       # actually delete
"""

from __future__ import annotations

import argparse

from sqlmodel import Session, delete, select

from db.models import Listing, Merchant, PriceHistory
from db.session import engine
from scrapers.ingest import MAX_PLAUSIBLE_PRICE_KES


def run(apply: bool = False) -> int:
    """Report (and optionally delete) implausibly-priced listings.

    Returns the number of offending listings found.
    """
    with Session(engine) as session:
        rows = session.exec(
            select(Listing, Merchant.name)
            .join(Merchant, Merchant.id == Listing.merchant_id)
            .where(Listing.price_kes > MAX_PLAUSIBLE_PRICE_KES)
            .order_by(Listing.price_kes.desc())
        ).all()

        if not rows:
            print(f"No listings above {MAX_PLAUSIBLE_PRICE_KES:,}. Nothing to do.")
            return 0

        print(f"{len(rows)} listing(s) above KSh {MAX_PLAUSIBLE_PRICE_KES:,}:\n")
        by_merchant: dict[str, int] = {}
        for listing, merchant_name in rows:
            by_merchant[merchant_name] = by_merchant.get(merchant_name, 0) + 1
            print(f"  {int(listing.price_kes):>20,}  {merchant_name[:24]:<24} {listing.title_on_merchant[:48]}")
        print("\nBy merchant:")
        for name, n in sorted(by_merchant.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>4}  {name}")

        if not apply:
            print("\nDry run. Re-run with --apply to delete these rows.")
            return len(rows)

        listing_ids = [listing.id for listing, _ in rows]
        # History first: the FK points this way, and an orphaned PriceHistory
        # row would let the product page's weekly chart redraw the bad price.
        history_deleted = session.exec(
            delete(PriceHistory).where(PriceHistory.listing_id.in_(listing_ids))
        ).rowcount
        session.exec(delete(Listing).where(Listing.id.in_(listing_ids)))
        session.commit()
        print(f"\nDeleted {len(listing_ids)} listing(s) and {history_deleted} history row(s).")
        return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this the script only reports.",
    )
    args = parser.parse_args()
    run(apply=args.apply)
