"""One-shot migration: add `marketing_opt_in BOOL DEFAULT FALSE` to `alert`.

`SQLModel.metadata.create_all` only creates tables that don't exist yet; it
never adds columns to existing tables. So the first deploy after adding the
`marketing_opt_in` field to `db/models.py` needs this script to actually
touch the schema.

Idempotent: uses "ADD COLUMN IF NOT EXISTS" on Postgres and a try/except on
SQLite (which doesn't support IF NOT EXISTS on ALTER TABLE). Safe to re-run.

Usage:
    python -m db.migrations.add_marketing_opt_in
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine


def run() -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            conn.execute(
                text(
                    "ALTER TABLE alert "
                    "ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE"
                )
            )
        else:
            # SQLite (local dev). ALTER TABLE ADD COLUMN doesn't support
            # IF NOT EXISTS pre-3.35; use a try/except.
            try:
                conn.execute(
                    text(
                        "ALTER TABLE alert "
                        "ADD COLUMN marketing_opt_in BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            except Exception as e:  # noqa: BLE001
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    print("column marketing_opt_in already exists — noop")
                    return
                raise
    print(f"added marketing_opt_in column to alert ({dialect})")


if __name__ == "__main__":
    run()
