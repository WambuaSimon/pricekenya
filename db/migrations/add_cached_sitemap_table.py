"""One-shot migration: create the `cachedsitemap` table.

Backs the sitemap-cache in app/routes/meta.py. Idempotent — same pattern
as the other migrations in this dir. See db.models.CachedSitemap for why.
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
                    CREATE TABLE IF NOT EXISTS cachedsitemap (
                        id            SERIAL PRIMARY KEY,
                        body          TEXT NOT NULL,
                        generated_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                        url_count     INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            )
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_cachedsitemap_generated_at ON cachedsitemap(generated_at)")
            )
        else:
            try:
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS cachedsitemap (
                            id            INTEGER PRIMARY KEY AUTOINCREMENT,
                            body          TEXT NOT NULL,
                            generated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            url_count     INTEGER NOT NULL DEFAULT 0
                        )
                        """
                    )
                )
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cachedsitemap_generated_at ON cachedsitemap(generated_at)"))
            except Exception as e:  # noqa: BLE001
                if "already exists" in str(e).lower():
                    print("cachedsitemap already exists — noop")
                    return
                raise
    print("cachedsitemap ready")


if __name__ == "__main__":
    run()
