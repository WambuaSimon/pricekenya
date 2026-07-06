"""One-shot migration: create the `click` table if it doesn't exist.

`SQLModel.metadata.create_all` normally handles new tables — this script only
matters on a Neon instance that was created before the `Click` model landed
in the codebase, where `create_all` might race or where we want a deliberate,
loggable step. Safe to re-run: `CREATE TABLE IF NOT EXISTS` is idempotent
on both Postgres and SQLite.

Usage:
    python -m db.migrations.add_click_table
"""

from __future__ import annotations

from sqlalchemy import inspect

from db.models import Click  # noqa: F401 — register with metadata
from db.session import engine


def run() -> None:
    insp = inspect(engine)
    if insp.has_table("click"):
        print("click table already exists — noop")
        return
    Click.__table__.create(bind=engine)
    print(f"created click table ({engine.dialect.name})")


if __name__ == "__main__":
    run()
