"""Create the `productredirect` table if it doesn't exist.

Idempotent — safe to run on every boot. See app/main.py lifespan for
where migrations are triggered.
"""

from __future__ import annotations

from sqlalchemy import inspect

from db.models import ProductRedirect  # noqa: F401 — register with metadata
from db.session import engine


def run() -> None:
    insp = inspect(engine)
    if insp.has_table("productredirect"):
        print("productredirect table already exists — noop")
        return
    ProductRedirect.__table__.create(bind=engine)
    print(f"created productredirect table ({engine.dialect.name})")


if __name__ == "__main__":
    run()
