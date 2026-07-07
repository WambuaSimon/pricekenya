from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from app.templating import templates
from db.models import Click, Listing, Merchant, Product
from db.session import get_session

router = APIRouter()


def _humanize_ago(ts: datetime | None) -> str:
    """Short compact ago-string for the homepage stats chip. Naive UTC in,
    "12m ago" / "3h ago" / "2d ago" out. Only used for display — precision
    beyond the current bucket doesn't matter."""
    if ts is None:
        return "—"
    delta = datetime.utcnow() - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


@router.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    # Ranking:
    #   1. offer_count DESC — showcase what the site is for (price comparison).
    #   2. clicks over the last 7d DESC — real-user signal on which listings
    #      matter, computed as a correlated scalar subquery so the main
    #      GROUP BY on Product.id stays clean (a JOIN through Click would
    #      multiply the min-price / offer-count aggregates).
    #   3. last_checked_at DESC — final tiebreak so untouched products don't
    #      tie forever.
    week_ago = datetime.utcnow() - timedelta(days=7)
    clicks_7d = (
        select(func.count(Click.id))
        .join(Listing, Listing.id == Click.listing_id)
        .where(Listing.product_id == Product.id)
        .where(Click.occurred_at >= week_ago)
        .correlate(Product)
        .scalar_subquery()
    )
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
            clicks_7d.desc(),
            func.max(Listing.last_checked_at).desc(),
        )
        .limit(24)
    ).all()

    # Hero stats — cheap counts + one MAX(). All three land in the same
    # gradient card at the top of home.html. Merchant count is limited to
    # merchants that actually have listings, so the number reflects live
    # coverage rather than the seed catalog.
    product_count = session.exec(select(func.count(Product.id))).one()
    merchant_count = session.exec(
        select(func.count(func.distinct(Listing.merchant_id)))
    ).one()
    last_listing_check = session.exec(select(func.max(Listing.last_checked_at))).one()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "rows": rows,
            "product_count": product_count or 0,
            "merchant_count": merchant_count or 0,
            "last_updated_ago": _humanize_ago(last_listing_check),
        },
    )


@router.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", session: Session = Depends(get_session)):
    q_clean = (q or "").strip()
    if q_clean:
        # LIKE wildcards from user input are escaped so `_` and `%` don't
        # explode query cost or leak into pattern semantics.
        like_arg = q_clean.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{like_arg}%"
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
    else:
        # Empty query — fall back to the multi-offer-first showcase used on
        # the home page. Better UX than a blank state when a user clears
        # the search box.
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
    # HTMX requests get just the results fragment
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "partials/_product_grid.html", {"rows": rows}
        )
    return templates.TemplateResponse(
        request, "search.html", {"rows": rows, "q": q_clean}
    )
