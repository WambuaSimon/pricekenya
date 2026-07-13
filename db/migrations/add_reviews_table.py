"""One-shot migration: create the `review` table.

Backs the user-review feature. Reviews stay hidden until the reviewer
verifies via email magic link — see Review.__doc__ for the flow.

Idempotent — checks for existence first, same pattern as add_click_table.
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
                    """
                    CREATE TABLE IF NOT EXISTS review (
                        id            SERIAL PRIMARY KEY,
                        product_id    INTEGER NOT NULL REFERENCES product(id),
                        email         TEXT NOT NULL,
                        display_name  TEXT NOT NULL,
                        rating        INTEGER NOT NULL,
                        title         TEXT,
                        body          TEXT NOT NULL,
                        pros          TEXT,
                        cons          TEXT,
                        verified_at   TIMESTAMP,
                        created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                        CONSTRAINT uq_review_product_email UNIQUE (product_id, email)
                    )
                    """
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_review_product_id ON review(product_id)")
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_review_email ON review(email)")
            )
        else:
            # SQLite path — no NOW() default, use CURRENT_TIMESTAMP; ignore
            # duplicate-table errors so re-running against an existing dev
            # DB stays a noop.
            try:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS review (
                            id            INTEGER PRIMARY KEY AUTOINCREMENT,
                            product_id    INTEGER NOT NULL REFERENCES product(id),
                            email         TEXT NOT NULL,
                            display_name  TEXT NOT NULL,
                            rating        INTEGER NOT NULL,
                            title         TEXT,
                            body          TEXT NOT NULL,
                            pros          TEXT,
                            cons          TEXT,
                            verified_at   TIMESTAMP,
                            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE (product_id, email)
                        )
                        """
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_review_product_id ON review(product_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_review_email ON review(email)"))
            except Exception as e:  # noqa: BLE001
                if "already exists" in str(e).lower():
                    print("review table already exists — noop")
                    return
                raise
    print("review table ready")


if __name__ == "__main__":
    run()
