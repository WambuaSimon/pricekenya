"""One-shot migration: add `embedding BLOB/BYTEA NULL` to `product`.

Backs Phase 1 (embedding-based reconciliation) — stores MiniLM 384-dim
float32 vectors (1536 bytes) for near-duplicate merging.

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
                text("ALTER TABLE product ADD COLUMN IF NOT EXISTS embedding BYTEA")
            )
        else:
            try:
                conn.execute(text("ALTER TABLE product ADD COLUMN embedding BLOB"))
            except Exception as e:  # noqa: BLE001
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print("column embedding already exists — noop")
                    return
                raise
    print(f"added embedding column to product ({dialect})")


if __name__ == "__main__":
    run()
