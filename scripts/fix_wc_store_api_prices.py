"""One-shot migration: correct 100x-inflated WC Store API listing prices.

Context: `scrapers/common/wc_store_api.py` was silently trusting the raw
`prices.price` string from the WC Store API without dividing by
`currency_minor_unit`. Merchants whose WC config used 2 decimal places
for KES (audiocom-ke, finetech-ke, newmatic-ke, techstore-ke) had every
listing stored at 100x the real price. Fixed in c06e8d5.

Without this migration, the next cron scrape would read the real price
(e.g. 69,000), find the stored price differs from it (6,900,000), and
log a PriceHistory row that the alert dispatcher reads as a MASSIVE
price drop — potentially emailing subscribed users about "prices
dropping 99%". This script corrects the DB in-place so the next scrape
sees no price change and fires no alerts.

Usage:
    # Dry-run (default) — reports what would change, writes nothing:
    python -m scripts.fix_wc_store_api_prices

    # Apply against the DB configured in DATABASE_URL:
    python -m scripts.fix_wc_store_api_prices --yes

Safety:
- Default is dry-run; --yes is required to write.
- Only touches listings whose merchant_id maps to one of the four
  audited-affected slugs. Any merchant added to the affected set later
  needs an explicit code change here.
- `--only-above` (default 1,000,000 KES) is a re-run guard: no legitimate
  Kenyan-retail SKU on these merchants costs above KSh 1M, so anything
  under that is either already-correct or a data anomaly and gets
  skipped. Idempotent — running the script twice is a no-op the second
  time.
- Deletes PriceHistory rows tied to the corrected listings — every
  historical row for these merchants is 100x too high, so keeping them
  would corrupt the price-history charts.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from sqlalchemy import delete
from sqlmodel import Session, select

from db.models import Listing, Merchant, PriceHistory
from db.session import engine

# Merchants whose WC store returns prices with currency_minor_unit=2 —
# audited on 2026-07-17 by hitting each site's /wp-json/wc/store/v1/products
# endpoint and reading the `prices.currency_minor_unit` field.
AFFECTED_SLUGS = frozenset({
    "audiocom-ke",
    "finetech-ke",
    "newmatic-ke",
    "techstore-ke",
})


def run(apply: bool, only_above: Decimal) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] Correcting WC Store API 100x price inflation for "
          f"{len(AFFECTED_SLUGS)} merchants: {sorted(AFFECTED_SLUGS)}")
    print(f"       Only touching listings priced above KSh {only_above:,}")
    print()

    with Session(engine) as session:
        merchants = session.exec(
            select(Merchant).where(Merchant.slug.in_(AFFECTED_SLUGS))  # type: ignore[attr-defined]
        ).all()
        if not merchants:
            print("No matching merchants found in the DB. Nothing to do.")
            return

        merchant_ids = [m.id for m in merchants if m.id is not None]
        slug_by_id = {m.id: m.slug for m in merchants}

        listings = session.exec(
            select(Listing).where(Listing.merchant_id.in_(merchant_ids))  # type: ignore[attr-defined]
        ).all()

        targets = [lst for lst in listings if lst.price_kes > only_above]

        by_merchant: dict[str, list[Listing]] = {}
        by_merchant_skipped: dict[str, int] = {}
        for lst in listings:
            slug = slug_by_id[lst.merchant_id]
            if lst.price_kes > only_above:
                by_merchant.setdefault(slug, []).append(lst)
            else:
                by_merchant_skipped[slug] = by_merchant_skipped.get(slug, 0) + 1

        print(f"{'merchant':<18} {'to fix':<8} {'skipped':<8} {'sample old':<15} {'sample new':<15}")
        print("-" * 72)
        for slug in sorted(set(by_merchant) | set(by_merchant_skipped)):
            rows = by_merchant.get(slug, [])
            skipped = by_merchant_skipped.get(slug, 0)
            if rows:
                sample = rows[0]
                old = sample.price_kes
                new = (old / Decimal(100)).quantize(Decimal("0.01"))
                print(f"{slug:<18} {len(rows):<8} {skipped:<8} {str(old):<15} {str(new):<15}")
            else:
                print(f"{slug:<18} {0:<8} {skipped:<8} (all skipped)")
        print()

        if not targets:
            print("Nothing to correct — every affected-merchant listing is "
                  "already below the threshold. Idempotent no-op.")
            return

        if not apply:
            print(f"Dry-run complete. Would correct {len(targets)} listings. "
                  "Re-run with --yes to apply.")
            return

        listing_ids: list[int] = []
        for lst in targets:
            lst.price_kes = (lst.price_kes / Decimal(100)).quantize(Decimal("0.01"))
            session.add(lst)
            if lst.id is not None:
                listing_ids.append(lst.id)

        deleted = 0
        if listing_ids:
            result = session.exec(
                delete(PriceHistory).where(
                    PriceHistory.listing_id.in_(listing_ids)  # type: ignore[attr-defined]
                )
            )
            deleted = getattr(result, "rowcount", 0) or 0

        session.commit()
        print(f"Corrected {len(targets)} listings; "
              f"deleted {deleted} inflated PriceHistory rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually write the corrections. Default is dry-run.",
    )
    parser.add_argument(
        "--only-above",
        type=Decimal,
        default=Decimal("1000000"),
        help=(
            "Only correct listings whose current price is above this "
            "threshold (KES). Makes the script idempotent and safe to "
            "re-run. Default: 1,000,000."
        ),
    )
    args = parser.parse_args()
    run(apply=args.yes, only_above=args.only_above)


if __name__ == "__main__":
    main()
