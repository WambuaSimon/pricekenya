"""Category landing pages at /c/<slug>.

Non-leaf categories aggregate products from every descendant leaf. Leaf
categories show just their own products. Empty categories render a "coming
soon" message so the page still exists for SEO before scrapers arrive.

Filters (`?brand=samsung&brand=xiaomi&storage=128&price_max=30000&in_stock=1`)
are parsed from the query string. Facet definitions live in `app/facets.py`;
this module only knows how to translate facets into SQLAlchemy clauses.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import String, cast
from sqlmodel import Session, func, select

from app.facets import Facet, facets_for
from app.templating import templates
from db.models import Category, Listing, Product
from db.session import get_session

router = APIRouter()


def _spec_as_text(key: str):
    """Return a SQL expression that reads Product.specs[key] as TEXT.

    Postgres (Neon prod) uses the JSON `->>` text-extraction operator;
    SQLite (dev) uses `json_extract` from the JSON1 extension. Product.specs
    is a plain JSON column (not JSONB), so SQLAlchemy's `.astext` accessor
    isn't available. This helper hides the dialect split so the same
    filter/available-values code paths work in both environments.

    The engine is looked up at call time (not import time) so tests that
    swap the module-level engine via a monkeypatch fixture see their
    replacement, not the process-level prod engine.
    """
    from db.session import engine

    if engine.dialect.name == "postgresql":
        return Product.specs.op("->>")(key)
    # cast to TEXT so a spec value of 128 (int) compares cleanly against
    # a query param of "128" (str) via .in_(...).
    return cast(func.json_extract(Product.specs, f"$.{key}"), String)


def _descendant_slugs(session: Session, root: Category) -> list[str]:
    """Return the slug list for root + every category beneath it in the tree."""
    slugs = [root.slug]
    frontier = [root.id]
    while frontier:
        next_ids = []
        for child in session.exec(select(Category).where(Category.parent_id.in_(frontier))).all():
            slugs.append(child.slug)
            next_ids.append(child.id)
        frontier = next_ids
    return slugs


def _spec_key(source: str) -> str | None:
    """Return the JSON key for a `specs.<key>` source, else None."""
    return source[6:] if source.startswith("specs.") else None


def _apply_enum(query, facet: Facet, values: list[str]):
    """Append an IN clause for a repeatable enum facet."""
    if not values:
        return query
    if facet.source == "brand":
        return query.where(Product.brand.in_(values))
    if key := _spec_key(facet.source):
        return query.where(_spec_as_text(key).in_(values))
    return query


def _parse_filters(request: Request, facets: list[Facet]) -> dict[str, list[str] | str | bool]:
    """Read query params according to the facet spec. Ignore unknown keys.

    Enum → list[str] (getlist honours ?brand=a&brand=b).
    Range → str (single value; template shows a number input).
    Bool → True/False (present with any truthy-ish value → True).
    """
    active: dict[str, list[str] | str | bool] = {}
    for f in facets:
        if f.kind == "enum":
            vals = request.query_params.getlist(f.key)
            if vals:
                active[f.key] = vals
        elif f.kind == "range":
            v = request.query_params.get(f.key)
            if v and v.strip():
                active[f.key] = v.strip()
        elif f.kind == "bool":
            v = request.query_params.get(f.key)
            if v and v.lower() not in ("0", "false", ""):
                active[f.key] = True
    return active


def _available_values(
    session: Session, category_slugs: list[str], facets: list[Facet]
) -> dict[str, list[str]]:
    """Distinct value sets for each enum facet in this category tree.

    Runs one small query per enum facet. Ordered numerically for spec
    facets (128 < 256 < 512) and lexically for brand. We never filter the
    available-values query by the ACTIVE filters — the sidebar should always
    show every option so the user can widen or swap dimensions.
    """
    out: dict[str, list[str]] = {}
    for f in facets:
        if f.kind != "enum":
            continue
        if f.source == "brand":
            rows = session.exec(
                select(Product.brand)
                .where(Product.category_slug.in_(category_slugs))
                .where(Product.brand.is_not(None))
                .distinct()
            ).all()
            out[f.key] = sorted({r for r in rows if r and r != "unknown"})
        elif key := _spec_key(f.source):
            expr = _spec_as_text(key)
            rows = session.exec(
                select(expr)
                .where(Product.category_slug.in_(category_slugs))
                .where(expr.is_not(None))
                .distinct()
            ).all()
            # Sort numerically when every value parses as a number, else lex.
            vals = [r for r in rows if r not in (None, "", "null")]
            try:
                out[f.key] = [str(v) for v in sorted({float(v) for v in vals})]
                # Trim trailing ".0" for integer-valued specs (128.0 → "128").
                out[f.key] = [v[:-2] if v.endswith(".0") else v for v in out[f.key]]
            except (TypeError, ValueError):
                out[f.key] = sorted(set(vals))
    return out


PAGE_SIZE = 48


@router.get("/c/{slug}", response_class=HTMLResponse)
def category_page(
    slug: str,
    request: Request,
    page: int = 1,
    session: Session = Depends(get_session),
):
    category = session.exec(select(Category).where(Category.slug == slug)).first()
    if not category:
        raise HTTPException(status_code=404)
    if page < 1:
        page = 1

    slugs = _descendant_slugs(session, category)

    # Sub-nav strategy: prefer the current category's own children (drill down).
    # If it's a leaf, show the parent's children instead so the nav doesn't
    # collapse — this lets a user on `/c/tablets` jump directly to Phones or
    # Accessories without navigating back up to the parent.
    children = session.exec(
        select(Category).where(Category.parent_id == category.id).order_by(Category.sort_order)
    ).all()
    if not children and category.parent_id is not None:
        children = session.exec(
            select(Category)
            .where(Category.parent_id == category.parent_id)
            .order_by(Category.sort_order)
        ).all()

    facets = facets_for(slug)
    active = _parse_filters(request, facets)
    available = _available_values(session, slugs, facets)

    # Base query: same shape as before — Product joined to Listing so we can
    # aggregate min_price + offer_count. Filters get layered in as WHERE
    # (enum/bool) or HAVING (range on aggregate) clauses.
    q = (
        select(
            Product,
            func.min(Listing.price_kes).label("min_price"),
            func.count(Listing.id).label("offer_count"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
    )

    for f in facets:
        val = active.get(f.key)
        if val is None:
            continue
        if f.kind == "enum":
            q = _apply_enum(q, f, val)  # type: ignore[arg-type]
        elif f.kind == "bool" and f.source == "in_stock":
            # in_stock filter runs against Listing rows — a Product survives
            # if it has AT LEAST ONE in-stock listing (that's what shoppers
            # care about; the merchant row on the product page can show the
            # rest as out-of-stock).
            q = q.where(Listing.in_stock.is_(True))

    q = q.group_by(Product.id)

    # HAVING clauses for range filters that operate on aggregates.
    price_max = active.get("price_max")
    if isinstance(price_max, str) and price_max.isdigit():
        q = q.having(func.min(Listing.price_kes) <= int(price_max))

    # Ordering: newest products first. Product.created_at is the moment a
    # new canonical_key first landed in the DB (via a scrape or retro
    # cleanup). Sorting by it means newly-discovered SKUs surface at the
    # top of a category page instead of getting buried at #197 behind the
    # already-multi-merchant popular products. Ties within a day fall back
    # to offer_count (multi-merchant products still rank higher within the
    # same day) then to freshness of the most recent listing check.
    q = q.order_by(
        Product.created_at.desc(),
        func.count(Listing.id).desc(),
        func.max(Listing.last_checked_at).desc(),
    )

    # Count total matching products up-front so we can render pagination
    # controls. Using a subquery keeps the aggregation semantics identical
    # to the main select (same filters, same GROUP BY, same HAVING).
    total_rows = session.exec(
        select(func.count()).select_from(q.subquery())
    ).one() or 0
    total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * PAGE_SIZE

    q = q.limit(PAGE_SIZE).offset(offset)
    rows = session.exec(q).all()

    # Hero stats — cheap counts over the category tree. Product/merchant
    # totals + a "compared" count (products with 2+ merchants) which is the
    # single stat that directly showcases the site's value prop: how much of
    # this category you can actually cross-shop.
    counts = session.exec(
        select(
            func.count(func.distinct(Product.id)),
            func.count(func.distinct(Listing.merchant_id)),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
    ).one()
    product_count, merchant_count = counts

    # "Compared" = products with listings from 2+ distinct merchants.
    compared_subq = (
        select(Product.id)
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
        .group_by(Product.id)
        .having(func.count(func.distinct(Listing.merchant_id)) >= 2)
        .subquery()
    )
    compared_count = session.exec(
        select(func.count()).select_from(compared_subq)
    ).one() or 0

    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "category": category,
            "children": children,
            "rows": rows,
            "product_count": product_count or 0,
            "merchant_count": merchant_count or 0,
            "compared_count": compared_count,
            "facets": facets,
            "active_filters": active,
            "available_values": available,
            "page": page,
            "total_pages": total_pages,
            "page_size": PAGE_SIZE,
            "total_matching": total_rows,
        },
    )
