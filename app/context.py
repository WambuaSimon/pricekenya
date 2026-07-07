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
    "power-energy": "⚡",
}


def _has_products_in_subtree(session: Session, root_id: int) -> bool:
    """Return True if any descendant leaf of `root_id` has at least one Product.

    Walks the tree with a simple BFS. Cheap because the tree has ~30 nodes and
    the Product.category_slug column is indexed.
    """
    frontier: list[int] = [root_id]
    slugs: list[str] = []
    visited: set[int] = set()
    while frontier:
        next_ids: list[int] = []
        for child in session.exec(
            select(Category).where(Category.parent_id.in_(frontier))
        ).all():
            if child.id in visited:
                continue
            visited.add(child.id)
            slugs.append(child.slug)
            next_ids.append(child.id)
        frontier = next_ids
    # Also include the root's own slug — some categories have products at the
    # top level rather than only on leaves.
    root = session.get(Category, root_id)
    if root:
        slugs.append(root.slug)
    if not slugs:
        return False
    exists = session.exec(
        select(Product.id).where(Product.category_slug.in_(slugs)).limit(1)
    ).first()
    return exists is not None


def get_nav_categories() -> list[dict]:
    """Return the top-level category buckets shown in the site nav.

    Excludes the single "electronics" root because it's a wrapper node,
    and hides any top-level whose subtree has zero products — an empty
    category link in the nav hurts trust more than it helps discovery.
    """
    with Session(engine) as s:
        root = s.exec(select(Category).where(Category.slug == "electronics")).first()
        if not root:
            rows = s.exec(
                select(Category)
                .where(Category.parent_id.is_not(None))
                .order_by(Category.sort_order)
            ).all()
        else:
            rows = s.exec(
                select(Category)
                .where(Category.parent_id == root.id)
                .order_by(Category.sort_order)
            ).all()

        return [
            {"slug": r.slug, "name": r.name, "icon": NAV_ICONS.get(r.slug, "")}
            for r in rows
            if _has_products_in_subtree(s, r.id)
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
