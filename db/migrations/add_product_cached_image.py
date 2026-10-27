"""One-shot migration: add `image_cached_url TEXT NULL` to `product`.

Deliberately a second column rather than overwriting `image_url`:

  image_url         where the image came from (the merchant). Provenance,
                    and the input the cache re-fetches from.
  image_cached_url  our own copy, on our own domain.

Keeping both means the cache is re-buildable from scratch, a cache miss
degrades to the old hotlink instead of a blank tile, and the whole feature
can be rolled back by ignoring one column.

Idempotent — same pattern as add_product_description.
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine


def run() -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text("ALTER TABLE product ADD COLUMN IF NOT EXISTS image_cached_url TEXT")
            )
        else:
            try:
                conn.execute(text("ALTER TABLE product ADD COLUMN image_cached_url TEXT"))
            except Exception as e:  # noqa: BLE001
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print("column image_cached_url already exists — noop")
                    return
                raise
    print(f"added image_cached_url column to product ({dialect})")


if __name__ == "__main__":
    run()
