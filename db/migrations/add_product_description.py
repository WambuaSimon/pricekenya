"""One-shot migration: add `description TEXT NULL` to `product`.

Idempotent — same pattern as add_marketing_opt_in.
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine


def run() -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text("ALTER TABLE product ADD COLUMN IF NOT EXISTS description TEXT")
            )
        else:
            try:
                conn.execute(text("ALTER TABLE product ADD COLUMN description TEXT"))
            except Exception as e:  # noqa: BLE001
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print("column description already exists — noop")
                    return
                raise
    print(f"added description column to product ({dialect})")


if __name__ == "__main__":
    run()
