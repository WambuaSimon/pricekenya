"""One-shot migration: add moderation columns to `review` + create
`reviewreport` table.

Columns on review:
  - edited_at        TIMESTAMP NULL — bumped on resubmit
  - hidden_at        TIMESTAMP NULL — admin hide (soft)
  - hidden_reason    TEXT NULL
  - marketing_opt_in BOOLEAN DEFAULT FALSE — DPA/GDPR consent for
    non-transactional outreach; separate from the review itself.

New table:
  - reviewreport (id, review_id, reason, reporter_ip_hash, created_at)
    with UNIQUE (review_id, reporter_ip_hash)

Idempotent — same pattern as the other migrations in this dir.
"""

from __future__ import annotations

from sqlalchemy import text

from db.session import engine


def _try(conn, sql: str) -> None:
    """Execute SQL, silently ignoring "already exists" / "duplicate column"."""
    try:
        conn.execute(text(sql))
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if "already exists" in msg or "duplicate column" in msg:
            return
        raise


def run() -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "postgresql":
            _try(conn, "ALTER TABLE review ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP")
            _try(conn, "ALTER TABLE review ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMP")
            _try(conn, "ALTER TABLE review ADD COLUMN IF NOT EXISTS hidden_reason TEXT")
            _try(conn, "ALTER TABLE review ADD COLUMN IF NOT EXISTS marketing_opt_in BOOLEAN NOT NULL DEFAULT FALSE")
            _try(
                conn,
                """
                CREATE TABLE IF NOT EXISTS reviewreport (
                    id                SERIAL PRIMARY KEY,
                    review_id         INTEGER NOT NULL REFERENCES review(id),
                    reason            TEXT,
                    reporter_ip_hash  TEXT NOT NULL,
                    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_report_reviewer UNIQUE (review_id, reporter_ip_hash)
                )
                """,
            )
            _try(
                conn,
                "CREATE INDEX IF NOT EXISTS ix_reviewreport_review_id ON reviewreport(review_id)",
            )
            _try(
                conn,
                "CREATE INDEX IF NOT EXISTS ix_reviewreport_reporter ON reviewreport(reporter_ip_hash)",
            )
            _try(
                conn,
                "CREATE INDEX IF NOT EXISTS ix_reviewreport_created_at ON reviewreport(created_at)",
            )
        else:
            _try(conn, "ALTER TABLE review ADD COLUMN edited_at TIMESTAMP")
            _try(conn, "ALTER TABLE review ADD COLUMN hidden_at TIMESTAMP")
            _try(conn, "ALTER TABLE review ADD COLUMN hidden_reason TEXT")
            _try(conn, "ALTER TABLE review ADD COLUMN marketing_opt_in BOOLEAN NOT NULL DEFAULT 0")
            _try(
                conn,
                """
                CREATE TABLE IF NOT EXISTS reviewreport (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_id         INTEGER NOT NULL REFERENCES review(id),
                    reason            TEXT,
                    reporter_ip_hash  TEXT NOT NULL,
                    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (review_id, reporter_ip_hash)
                )
                """,
            )
            _try(
                conn,
                "CREATE INDEX IF NOT EXISTS ix_reviewreport_review_id ON reviewreport(review_id)",
            )
            _try(
                conn,
                "CREATE INDEX IF NOT EXISTS ix_reviewreport_reporter ON reviewreport(reporter_ip_hash)",
            )
    print("review moderation columns + reviewreport ready")


if __name__ == "__main__":
    run()
