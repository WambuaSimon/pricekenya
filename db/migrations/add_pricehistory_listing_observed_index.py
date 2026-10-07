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
query silently stops being indexed.

The lock a plain build takes is SHARE, not ACCESS EXCLUSIVE: it blocks
writes to pricehistory for the length of the build but still permits
reads, so the site keeps serving pages throughout. Seconds against a
56MB heap.

Two consequences of running it from the lifespan hook, both acceptable
but worth knowing: readiness is delayed until it finishes, so /healthz
stays down for the build (fine at seconds, not fine if this table grows
an order of magnitude); and a scrape running concurrently will have its
PriceHistory inserts blocked until the build completes, since those are
exactly the writes SHARE excludes. Scheduled scrapes fire at ~06:17 and
~18:17 UTC, so prefer deploying the first boot outside those windows.

If the table grows to where that stall matters, this should become a
CONCURRENTLY build run by hand with an explicit pg_index.indisvalid
check, not a cleverer version of this file.
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
