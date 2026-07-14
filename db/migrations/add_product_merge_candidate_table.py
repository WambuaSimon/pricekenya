"""One-shot migration: create the `productmergecandidate` table if it doesn't exist.

Backs Phase 1 (embedding review queue) — pairs in the 0.90–0.95 cosine band
land here for manual review at /admin/merge-review.

Same idempotent pattern as add_click_table.

Usage:
    python -m db.migrations.add_product_merge_candidate_table
"""

from __future__ import annotations

from sqlalchemy import inspect

from db.models import ProductMergeCandidate  # noqa: F401 — register with metadata
from db.session import engine


def run() -> None:
    insp = inspect(engine)
    if insp.has_table("productmergecandidate"):
        print("productmergecandidate table already exists — noop")
        return
    ProductMergeCandidate.__table__.create(bind=engine)
    print(f"created productmergecandidate table ({engine.dialect.name})")


if __name__ == "__main__":
    run()
