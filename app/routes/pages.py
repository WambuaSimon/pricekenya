from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from app.templating import templates
from db.models import Listing, Product
from db.session import get_session

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    # Multi-offer first — the home page should showcase what the site is
    # actually for (price comparison), not the most-recently-crawled long
    # tail. Recency is only the tie-breaker.
    rows = session.exec(
        select(
            Product,
            func.min(Listing.price_kes).label("min_price"),
            func.count(Listing.id).label("offer_count"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .group_by(Product.id)
        .order_by(
            func.count(Listing.id).desc(),
            func.max(Listing.last_checked_at).desc(),
        )
        .limit(24)
    ).all()
    return templates.TemplateResponse(request, "home.html", {"rows": rows})


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", session: Session = Depends(get_session)):
    q_clean = (q or "").strip()
    rows = []
    if q_clean:
        like = f"%{q_clean.lower()}%"
        rows = session.exec(
            select(
                Product,
                func.min(Listing.price_kes).label("min_price"),
                func.count(Listing.id).label("offer_count"),
            )
            .join(Listing, Listing.product_id == Product.id)
            .where(func.lower(Product.title).like(like))
            .group_by(Product.id)
            .limit(50)
        ).all()
    # HTMX requests get just the results fragment
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "partials/_product_grid.html", {"rows": rows}
        )
    return templates.TemplateResponse(
        request, "search.html", {"rows": rows, "q": q_clean}
    )
