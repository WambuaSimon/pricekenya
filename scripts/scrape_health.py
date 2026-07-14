"""Per-merchant scrape health report.

Prints a table with each merchant's listing count, last-scrape timestamp,
and how many hours ago that was. Merchants stale >24h are flagged (that's
about 4x the 6-hourly cron interval).

Usage:
    python -m scripts.scrape_health
    python -m scripts.scrape_health --json          # machine-readable
    python -m scripts.scrape_health --stale-hours 12  # narrower alert threshold

The `merchant_health()` function is also imported by the /admin/scrapes
dashboard so both surfaces share one query implementation.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlmodel import Session, func, select

from db.models import Listing, Merchant
from db.session import engine


@dataclass
class MerchantHealth:
    """One row of the health report."""

    slug: str
    name: str
    listing_count: int
    in_stock_count: int
    last_checked_at: datetime | None  # None only if merchant has zero listings
    hours_since_last_check: float | None

    def to_row(self) -> dict:
        return asdict(self)


def merchant_health(session: Session) -> list[MerchantHealth]:
    """Return one MerchantHealth per Merchant, sorted by staleness DESC.

    Merchants with zero listings appear at the bottom with `None` timestamp.
    """
    now = datetime.now(UTC)

    # Two small aggregating queries. Doing the in-stock filter in the same
    # query as the total count needs a dialect-specific COUNT-with-FILTER
    # or CASE cast; two queries is trivially cheaper than either at our
    # scale (~60 merchants) and stays portable across sqlite/postgres.
    total_rows = session.exec(
        select(
            Merchant.slug,
            Merchant.name,
            func.count(Listing.id).label("listing_count"),
            func.max(Listing.last_checked_at).label("last_checked_at"),
        )
        .join(Listing, Listing.merchant_id == Merchant.id, isouter=True)
        .group_by(Merchant.id)
    ).all()

    stock_rows = session.exec(
        select(Merchant.slug, func.count(Listing.id))
        .join(Listing, Listing.merchant_id == Merchant.id)
        .where(Listing.in_stock.is_(True))
        .group_by(Merchant.slug)
    ).all()
    stock_by_slug = dict(stock_rows)

    out: list[MerchantHealth] = []
    for slug, name, listing_count, last_checked_at in total_rows:
        if last_checked_at is not None:
            # SQLModel/Postgres returns tz-aware datetimes; SQLite returns
            # naïve. Normalise both to UTC-aware so the subtraction below
            # doesn't blow up with "can't subtract offset-naive and offset-
            # aware datetimes".
            if last_checked_at.tzinfo is None:
                last_checked_at = last_checked_at.replace(tzinfo=UTC)
            hours = (now - last_checked_at).total_seconds() / 3600.0
        else:
            hours = None
        out.append(
            MerchantHealth(
                slug=slug,
                name=name,
                listing_count=listing_count or 0,
                in_stock_count=stock_by_slug.get(slug, 0),
                last_checked_at=last_checked_at,
                hours_since_last_check=hours,
            )
        )

    # Stale first (largest hours_since_last_check first). None sorts to the
    # end so merchants that have never been scraped land at the bottom of
    # the "watch this" list rather than the top.
    out.sort(
        key=lambda r: (r.hours_since_last_check is None, -(r.hours_since_last_check or 0)),
    )
    return out


def _format_row(r: MerchantHealth, *, stale_hours: float, use_colour: bool) -> str:
    if r.hours_since_last_check is None:
        staleness = "never"
        colour_start, colour_end = ("", "")
    elif r.hours_since_last_check > stale_hours:
        staleness = f"{r.hours_since_last_check:>6.1f}h STALE"
        colour_start, colour_end = ("\033[31m", "\033[0m") if use_colour else ("", "")
    else:
        staleness = f"{r.hours_since_last_check:>6.1f}h"
        colour_start, colour_end = ("", "")
    last = (
        r.last_checked_at.strftime("%Y-%m-%d %H:%M UTC") if r.last_checked_at else "—"
    )
    return (
        f"{colour_start}{r.slug:<22} "
        f"{r.listing_count:>6}  "
        f"{r.in_stock_count:>6}  "
        f"{last:<20}  "
        f"{staleness:<14}"
        f"{colour_end}"
    )


def _print_table(rows: list[MerchantHealth], *, stale_hours: float) -> None:
    use_colour = sys.stdout.isatty()
    header = f"{'MERCHANT':<22} {'LISTINGS':>6}  {'INSTOCK':>6}  {'LAST CHECKED':<20}  {'AGE':<14}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(_format_row(r, stale_hours=stale_hours, use_colour=use_colour))
    stale = sum(1 for r in rows if r.hours_since_last_check is not None and r.hours_since_last_check > stale_hours)
    never = sum(1 for r in rows if r.hours_since_last_check is None)
    print()
    print(
        f"Total: {len(rows)} merchants  |  {stale} stale (> {stale_hours:g}h)  "
        f"|  {never} never scraped"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report per-merchant scrape freshness against the current DB."
    )
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=24.0,
        help="Merchants not scraped in this many hours are flagged (default 24).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit newline-delimited JSON instead of a table (for scripts).",
    )
    args = parser.parse_args()

    with Session(engine) as s:
        rows = merchant_health(s)

    if args.json:
        for r in rows:
            row = r.to_row()
            row["last_checked_at"] = (
                row["last_checked_at"].isoformat() if row["last_checked_at"] else None
            )
            print(jsonlib.dumps(row))
    else:
        _print_table(rows, stale_hours=args.stale_hours)


if __name__ == "__main__":
    main()
