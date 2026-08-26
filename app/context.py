"""Request-lifetime context providers used across templates."""

from __future__ import annotations

import time
from functools import lru_cache
from urllib.parse import quote

from sqlmodel import Session, select

from app.config import settings
from db.models import Category, Product
from db.session import engine


def whatsapp_href(text: str | None = None) -> str | None:
    """Return a `wa.me/<number>?text=<msg>` URL, or None if unset.

    Templates check the return value to decide whether to render the
    share button / floating chat pill at all — a missing number should
    silently hide the feature, not surface a broken link.
    """
    num = (settings.pricekenya_whatsapp_number or "").strip()
    if not num:
        return None
    if text:
        return f"https://wa.me/{num}?text={quote(text)}"
    return f"https://wa.me/{num}"

# Stroke-icon key + short nav label per top-level category slug. The key
# indexes _ICON_PATHS in partials/_icons.html; `short` is what the horizontal
# nav strip renders, since the full names ("Phones, Tablets and Accessories")
# blow the strip past one line.
#
# Superseded NAV_ICONS below for every surface that has been revamped. That
# dict stays because watchlist.html and any not-yet-revamped template still
# read `cat.icon`.
NAV_STROKE_ICONS: dict[str, str] = {
    "phones-tablets-accessories": "phones",
    "computing": "computing",
    "tvs": "tv",
    "audio": "audio",
    "cameras": "camera",
    "appliances": "appliances",
    "gaming": "gaming",
    "power-energy": "power",
    "home-kitchen": "home",
}

NAV_SHORT_NAMES: dict[str, str] = {
    "phones-tablets-accessories": "Phones",
    "computing": "Computing",
    "tvs": "TVs",
    "audio": "Audio",
    "cameras": "Cameras",
    "appliances": "Appliances",
    "gaming": "Gaming",
    "power-energy": "Solar",
    "home-kitchen": "Home",
}


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


# Leaf-category → emoji, used as a graceful fallback when Product.image_url
# is missing or points at a merchant placeholder. Keeps product cards from
# rendering as blank grey squares.
LEAF_ICONS: dict[str, str] = {
    "phones": "📱",
    "tablets": "📱",
    "phone-tablet-accessories": "🔌",
    "laptops": "💻",
    "peripherals-accessories": "⌨️",
    "tvs": "📺",
    "audio": "🎧",
    "cameras": "📷",
    "refrigerators": "❄️",
    "freezers": "❄️",
    "water-dispensers": "💧",
    "washers-dryers": "🧺",
    "cooking": "🍳",
    "blenders": "🥤",
    "toasters": "🍞",
    "kettles": "🫖",
    "ironing-laundry": "🧺",
    "inverters": "⚡",
    "solar-panels": "☀️",
    "solar-batteries": "🔋",
    "console-accessories": "🎮",
}


def product_placeholder_icon(product) -> str:
    """Return an emoji-fallback icon for a product with no image_url.

    Kept for watchlist.html, which is out of scope for the revamp. Revamped
    templates call product_fallback_label() instead — do not change this
    signature without checking that caller.
    """
    slug = getattr(product, "category_slug", None) or ""
    return LEAF_ICONS.get(slug, "📦")


def product_fallback_label(product) -> str:
    """Return the text drawn on a product's image-fallback tile.

    The revamp replaced the emoji fallback with the brand name set in `faint`
    on a `tile` box. Brand is the useful thing to show: ~7% of merchant image
    URLs hotlink-block (403) and those cards are otherwise anonymous, so the
    brand is the only identifying mark left before the title.

    Falls back to the first word of the title when brand is empty, and to ""
    when there is nothing to draw — templates render the box either way, so
    an empty label degrades to a plain tile rather than to broken markup.
    Small slots render `label[:1]`; the caller decides, not this helper.
    """
    brand = (getattr(product, "brand", None) or "").strip()
    if brand:
        # Brands are stored lowercase ("samsung"); the tile is a display
        # surface, so title-case it.
        return brand.title()
    title = (getattr(product, "title", None) or "").strip()
    return title.split(" ", 1)[0] if title else ""


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


# Nav bar renders on every page (twice — base.html + _sidebar_nav.html) and
# each call fires 8-15 SELECTs (root lookup + BFS + Product existence probe
# per top-level). At 500 page views/day that's ~15k queries/day burning Neon
# compute hours for a result that changes only when a category gets its first
# product. 10-minute TTL is invisible to users and drops nav queries to ~144/day
# per worker.
_NAV_CACHE_TTL_SECONDS = 600
_nav_cache: tuple[list[dict], float] | None = None


def get_nav_categories() -> list[dict]:
    global _nav_cache
    now = time.monotonic()
    cached = _nav_cache
    if cached is not None and (now - cached[1]) < _NAV_CACHE_TTL_SECONDS:
        return cached[0]
    result = _compute_nav_categories()
    _nav_cache = (result, now)
    return result


def _compute_nav_categories() -> list[dict]:
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
            {
                "slug": r.slug,
                "name": r.name,
                "short": NAV_SHORT_NAMES.get(r.slug, r.name),
                "icon_key": NAV_STROKE_ICONS.get(r.slug, ""),
                "icon": NAV_ICONS.get(r.slug, ""),
            }
            for r in rows
            if _has_products_in_subtree(s, r.id)
        ]


@lru_cache(maxsize=1)
def get_category_names() -> dict[str, str]:
    """slug -> display name for every category in the tree.

    Used for the eyebrow label on the homepage gap cards. The tree only
    changes on deploy, so a process-lifetime cache is the right TTL.
    """
    with Session(engine) as s:
        return {c.slug: c.name for c in s.exec(select(Category)).all()}


_counts_cache: tuple[dict[str, int], float] | None = None


def get_category_product_counts() -> dict[str, int]:
    """Product count per top-level nav category, for the homepage browse grid.

    Counts products with at least one in-stock listing, matching the rule
    every other surface uses (home grid, category grid, product page,
    sitemap). A browse card advertising 1,904 appliances that resolves to a
    grid of 1,100 is the same class of lie the in_stock restriction was
    added to kill.

    Shares the nav's 10-minute TTL. The figure moves only as the scrapers
    run, and the walk underneath is 9 subtree expansions plus one grouped
    count, which is not something to repeat per pageview.
    """
    global _counts_cache
    now = time.monotonic()
    cached = _counts_cache
    if cached is not None and (now - cached[1]) < _NAV_CACHE_TTL_SECONDS:
        return cached[0]
    result = _compute_category_product_counts()
    _counts_cache = (result, now)
    return result


def _compute_category_product_counts() -> dict[str, int]:
    from sqlalchemy import func

    from db.models import Listing

    counts: dict[str, int] = {}
    with Session(engine) as s:
        for cat in get_nav_categories():
            top = s.exec(select(Category).where(Category.slug == cat["slug"])).first()
            if not top:
                continue
            slugs = _subtree_slugs(s, top)
            counts[cat["slug"]] = (
                s.exec(
                    select(func.count(func.distinct(Product.id)))
                    .join(Listing, Listing.product_id == Product.id)
                    .where(Product.category_slug.in_(slugs))
                    .where(Listing.in_stock.is_(True))
                ).one()
                or 0
            )
    return counts


def _subtree_slugs(session: Session, root: Category) -> list[str]:
    """Every category slug at or beneath `root`, including the root itself."""
    slugs = [root.slug]
    frontier = [root.id]
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
    return slugs


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


# Product.category_slug is effectively immutable for a given product slug, and
# a category's position in the tree only changes on deploy. Cache both lookups
# without a TTL — process restart on deploy is the natural invalidation.
@lru_cache(maxsize=4096)
def _top_slug_for_category(cat_slug: str) -> str | None:
    with Session(engine) as s:
        return _walk_to_top_level_slug(s, cat_slug)


@lru_cache(maxsize=4096)
def _top_slug_for_product(product_slug: str) -> str | None:
    with Session(engine) as s:
        product = s.exec(select(Product).where(Product.slug == product_slug)).first()
        if not product:
            return None
        return _walk_to_top_level_slug(s, product.category_slug)


def get_active_top_slug(request) -> str | None:
    """Return the top-level nav slug that should be marked active for the
    given request. Works for /c/<slug> and /p/<slug> — everything else
    returns None (home, search, healthz, etc.)."""
    path = request.url.path if hasattr(request, "url") else ""
    if path.startswith("/c/"):
        return _top_slug_for_category(path[3:].split("/", 1)[0])
    if path.startswith("/p/"):
        return _top_slug_for_product(path[3:].split("/", 1)[0])
    return None
