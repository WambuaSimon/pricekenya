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
    children = session.exec(
        select(Category).where(Category.parent_id == category.id).order_by(Category.sort_order)
    ).all()

    rows = session.exec(
        select(
            Product,
            func.min(Listing.price_kes).label("min_price"),
            func.count(Listing.id).label("offer_count"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
        .group_by(Product.id)
        .order_by(func.max(Listing.last_checked_at).desc())
        .limit(48)
    ).all()

    return templates.TemplateResponse(
        request,
        "category.html",
        {"category": category, "children": children, "rows": rows},
    )
