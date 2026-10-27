"""One-shot migration: create `productimagecandidate`.

Queue of images sourced from outside the merchant catalog, awaiting human
approval. See db/models.ProductImageCandidate for why nothing auto-publishes.

Idempotent — CREATE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine

_PG = """
CREATE TABLE IF NOT EXISTS productimagecandidate (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES product(id),
    image_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source TEXT NOT NULL,
    matched_title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_at TIMESTAMPTZ NULL,
    reviewer_note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_imagecandidate_product_source UNIQUE (product_id, source)
)
"""

_SQLITE = """
CREATE TABLE IF NOT EXISTS productimagecandidate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES product(id),
    image_url TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source TEXT NOT NULL,
    matched_title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_at TIMESTAMP NULL,
    reviewer_note TEXT NULL,
    created_at TIMESTAMP NOT NULL,
    CONSTRAINT uq_imagecandidate_product_source UNIQUE (product_id, source)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_productimagecandidate_product_id ON productimagecandidate (product_id)",
    "CREATE INDEX IF NOT EXISTS ix_productimagecandidate_status ON productimagecandidate (status)",
    "CREATE INDEX IF NOT EXISTS ix_productimagecandidate_source ON productimagecandidate (source)",
    "CREATE INDEX IF NOT EXISTS ix_productimagecandidate_created_at ON productimagecandidate (created_at)",
)


def run() -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        conn.execute(text(_PG if dialect == "postgresql" else _SQLITE))
        for stmt in _INDEXES:
            conn.execute(text(stmt))
    print(f"productimagecandidate table ready ({dialect})")


if __name__ == "__main__":
    run()
