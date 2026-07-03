"""Request-lifetime context providers used across templates."""

from __future__ import annotations

from sqlmodel import Session, select

from db.models import Category, Product
from db.session import engine

# Emoji per top-level category slug — hardcoded because the tree is stable
# and the icons are a UI concern, not data.
NAV_ICONS: dict[str, str] = {
    "phones-tablets-accessories": "📱",
    "computing": "💻",
    "tvs": "📺",
    "audio": "🎧",
    "cameras": "📷",
    "appliances": "🍳",
    "gaming": "🎮",
}


def get_nav_categories() -> list[dict]:
    """Return the top-level category buckets shown in the site nav.

    Excludes the single "electronics" root because it's a wrapper node —
    the useful buckets are its immediate children (Phones/Tablets, Computing,
    TVs, Audio, Cameras, Appliances, Gaming).
    """
    with Session(engine) as s:
        root = s.exec(select(Category).where(Category.slug == "electronics")).first()
        if not root:
            rows = s.exec(
                select(Category)
                .where(Category.parent_id.is_not(None))
                .order_by(Category.sort_order)
            ).all()
            return [
                {"slug": r.slug, "name": r.name, "icon": NAV_ICONS.get(r.slug, "")}
                for r in rows
            ]

        rows = s.exec(
            select(Category)
            .where(Category.parent_id == root.id)
            .order_by(Category.sort_order)
        ).all()
        return [
            {"slug": r.slug, "name": r.name, "icon": NAV_ICONS.get(r.slug, "")}
            for r in rows
        ]


def _walk_to_top_level_slug(session: Session, current_slug: str) -> str | None:
    """Walk up the Category parent chain until we hit a direct child of the
    'electronics' root. That's the slug the top-nav should highlight."""
    cat = session.exec(select(Category).where(Category.slug == current_slug)).first()
    if not cat:
        return None
    while cat.parent_id:
        parent = session.exec(
            select(Category).where(Category.id == cat.parent_id)
        ).first()
        if not parent or parent.slug == "electronics":
            return cat.slug
        cat = parent
    return None


def get_active_top_slug(request) -> str | None:
    """Return the top-level nav slug that should be marked active for the
    given request. Works for /c/<slug> and /p/<slug> — everything else
    returns None (home, search, healthz, etc.)."""
    path = request.url.path if hasattr(request, "url") else ""
    slug: str | None = None
    if path.startswith("/c/"):
        slug = path[3:].split("/", 1)[0]
    elif path.startswith("/p/"):
        product_slug = path[3:].split("/", 1)[0]
        with Session(engine) as s:
            product = s.exec(
                select(Product).where(Product.slug == product_slug)
            ).first()
            if product:
                slug = product.category_slug

    if not slug:
        return None

    with Session(engine) as s:
        return _walk_to_top_level_slug(s, slug)
