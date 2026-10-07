"""One-shot migration: add the composite `(listing_id, observed_at)` index
to `pricehistory`.

See db.models.PriceHistory for why the pair is indexed together and why
listing_id leads. This file only exists because the table predates the
declaration — SQLModel.metadata.create_all() in db.session.init_db() adds
indexes for new tables but never touches an existing one.

Idempotent — same pattern as the other migrations in this dir.

Plain CREATE INDEX, not CONCURRENTLY, on purpose. CONCURRENTLY can't run
inside a transaction (which `engine.begin()` opens), and its failure mode is
worse here than the lock it avoids: a failed concurrent build leaves an
INVALID index behind that `IF NOT EXISTS` then happily skips on every
subsequent boot, so the migration silently stops being idempotent and the
query silently stops being indexed. The lock this takes is ACCESS EXCLUSIVE
on pricehistory for the length of the build — seconds against a 56MB heap —
and it happens in the lifespan hook before the instance starts taking
traffic. If the table grows to where that stall matters, this should become
a CONCURRENTLY build run by hand with an explicit pg_index.indisvalid check,
not a cleverer version of this file.
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine


def run() -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        # Identical statement on both dialects — SQLite has supported
        # CREATE INDEX IF NOT EXISTS since 3.8.0 (2013), so no split like
        # the ADD COLUMN migrations need.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_pricehistory_listing_observed "
                "ON pricehistory(listing_id, observed_at)"
            )
        )
    print(f"ix_pricehistory_listing_observed ready ({dialect})")


if __name__ == "__main__":
    run()
