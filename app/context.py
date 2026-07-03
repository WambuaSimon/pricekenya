"""Request-lifetime context providers used across templates.

The category nav appears on every page. We used to cache the lookup with
@lru_cache for the process lifetime, but that broke on prod when Render's
app booted while the Category table was empty (the cache stuck on []).
The table has ~30 rows and the query is trivial, so we just run it per
render — well under 1ms and immune to boot-time race conditions.
"""

from __future__ import annotations

from sqlmodel import Session, select

from db.models import Category
from db.session import engine


def get_nav_categories() -> list[dict]:
    """Return the top-level category buckets shown in the site nav.

    Excludes the single "electronics" root because it's a wrapper node —
    the useful buckets are its immediate children (Phones/Tablets, Computing,
    TVs, Audio, Cameras, Appliances, Gaming).
    """
    with Session(engine) as s:
        root = s.exec(select(Category).where(Category.slug == "electronics")).first()
        if not root:
            # Fallback: no root defined yet — return every non-root category.
            rows = s.exec(
                select(Category)
                .where(Category.parent_id.is_not(None))
                .order_by(Category.sort_order)
            ).all()
            return [{"slug": r.slug, "name": r.name} for r in rows]

        rows = s.exec(
            select(Category)
            .where(Category.parent_id == root.id)
            .order_by(Category.sort_order)
        ).all()
        return [{"slug": r.slug, "name": r.name} for r in rows]
