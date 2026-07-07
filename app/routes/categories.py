"""Category landing pages at /c/<slug>.

Non-leaf categories aggregate products from every descendant leaf. Leaf
categories show just their own products. Empty categories render a "coming
soon" message so the page still exists for SEO before scrapers arrive.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from app.templating import templates
from db.models import Category, Listing, Product
from db.session import get_session

router = APIRouter()


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


@router.get("/c/{slug}", response_class=HTMLResponse)
def category_page(slug: str, request: Request, session: Session = Depends(get_session)):
    category = session.exec(select(Category).where(Category.slug == slug)).first()
    if not category:
        raise HTTPException(status_code=404)

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

    # Prioritise multi-offer products: this is a price-comparison site, so
    # anything with 2+ merchants stocking it should show up first regardless
    # of when it was last scraped. Recency is only the tie-breaker.
    rows = session.exec(
        select(
            Product,
            func.min(Listing.price_kes).label("min_price"),
            func.count(Listing.id).label("offer_count"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
        .group_by(Product.id)
        .order_by(
            func.count(Listing.id).desc(),
            func.max(Listing.last_checked_at).desc(),
        )
        .limit(48)
    ).all()

    # Hero stats — one query, one row. Counts and price extremes over every
    # product in this category tree. Everything nullable so an empty category
    # still renders the hero (just without a price-range chip).
    stats = session.exec(
        select(
            func.count(func.distinct(Product.id)),
            func.count(func.distinct(Listing.merchant_id)),
            func.min(Listing.price_kes),
            func.max(Listing.price_kes),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
    ).one()
    product_count, merchant_count, min_price, max_price = stats

    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "category": category,
            "children": children,
            "rows": rows,
            "product_count": product_count or 0,
            "merchant_count": merchant_count or 0,
            "min_price": min_price,
            "max_price": max_price,
        },
    )
