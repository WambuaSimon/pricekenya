"""Drop and recreate all tables. Destroys ALL data. One-shot migration tool.

We don't (yet) use Alembic. When the schema changes in a way SQLAlchemy's
`create_all` can't handle (new column on an existing table), this script wipes
and recreates. It's fine for v0 where no user data is at stake; add Alembic
before that stops being true.

Usage:
    python -m db.reset --confirm
"""

from __future__ import annotations

import sys

from sqlmodel import SQLModel

from db.session import engine


def run(confirm: bool) -> None:
    if not confirm:
        print("Refusing to run without --confirm. This DROPS all tables.")
        sys.exit(2)

    # Import models to register their metadata.
    from db import models  # noqa: F401

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    print("Dropped and recreated all tables.")


if __name__ == "__main__":
    run("--confirm" in sys.argv[1:])
