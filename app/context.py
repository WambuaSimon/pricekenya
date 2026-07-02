"""Request-lifetime context providers used across templates.

The category nav appears on every page, so we want its data source in one
place — not repeated in each route. We inject `nav_categories` into the
template environment as globals refreshed per request via a lightweight
middleware would be overkill for v0; instead, the templating module reads
this on every render.
"""

from __future__ import annotations

from functools import lru_cache

from sqlmodel import Session, select

from db.models import Category
from db.session import engine


@lru_cache(maxsize=1)
def _top_level_categories_cached() -> list[dict]:
    """Fetch top-level categories once per process. They're seeded, not scraped,
    so cache invalidation isn't a concern. Clear the cache in tests if needed."""
    with Session(engine) as s:
        rows = s.exec(
            select(Category).where(Category.parent_id.is_not(None)).order_by(Category.sort_order)
        ).all()
        # Filter to second-level categories under the single 'electronics' root
        # so the nav shows the actionable buckets, not the root itself.
        root = s.exec(select(Category).where(Category.slug == "electronics")).first()
        if not root:
            return [{"slug": r.slug, "name": r.name} for r in rows]
        return [
            {"slug": r.slug, "name": r.name}
            for r in rows
            if r.parent_id == root.id
        ]


def get_nav_categories() -> list[dict]:
    return _top_level_categories_cached()
