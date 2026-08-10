import random
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from app.templating import templates
from db.models import Click, Listing, Merchant, Product
from db.session import get_session

router = APIRouter()

# Home page rotation config. The pool is ordered by the same
# offer_count → clicks_7d → freshness ranking as before; the shuffle +
# category cap is what makes the grid feel fresh across visits.
_HOME_POOL_SIZE = 150       # how many top-ranked products enter the rotation pool
_HOME_DISPLAY = 24          # how many the grid actually shows
_HOME_MAX_PER_CATEGORY = 4  # cap per top-level category slug for visual diversity
_HOME_ROTATION_HOURS = 6    # bucket width → 4 rotations/day

# Featured "head-to-head" product in the hero. Draws from the top slice of
# the pool so the highlighted product actually has enough merchant offers
# to make the comparison compelling. 30 * 6h buckets = ~7.5 days to cycle
# through the top slice.
_FEATURED_POOL_SLICE = 30
_FEATURED_MAX_OFFERS = 4    # cards shown in the hero comparison strip


def _time_bucket(now: datetime | None = None) -> int:
    """Deterministic shuffle seed. Same seed for every request inside the
    same 6h window so a page refresh returns the same order (avoids the
    jarring reshuffle-on-every-visit feel) while still cycling 4× a day."""
    now = now or datetime.utcnow()
    return now.timetuple().tm_yday * 24 + now.hour // _HOME_ROTATION_HOURS


def _select_featured(pool, bucket_seed: int, slice_size: int):
    """Deterministically pick one product from the top slice of the pool
    to headline the hero. Rotates as the bucket_seed advances.

    Returns (Product, min_price, offer_count) or None if the pool is empty.
    """
    if not pool:
        return None
    top_slice = pool[:slice_size]
    return top_slice[bucket_seed % len(top_slice)]


def _fetch_featured_offers(
    session: Session, product_id: int, limit: int
) -> tuple[list[tuple], object | None, object | None]:
    """Fetch top-N in-stock offers for the featured product, sorted cheapest
    first. Returns (offers, savings_abs, savings_pct) where offers is a list
    of (Listing, Merchant) tuples and savings compares cheapest vs most
    expensive shown."""
    offers = session.exec(
        select(Listing, Merchant)
        .join(Merchant, Merchant.id == Listing.merchant_id)
        .where(Listing.product_id == product_id)
        .where(Listing.in_stock.is_(True))
        .order_by(Listing.price_kes.asc())
        .limit(limit)
    ).all()
    if len(offers) < 2:
        return offers, None, None
    cheapest = offers[0][0].price_kes
    dearest = offers[-1][0].price_kes
    savings_abs = dearest - cheapest
    savings_pct = round((savings_abs / dearest) * 100) if dearest else None
    return offers, savings_abs, savings_pct


def _select_home_rows(pool, bucket_seed: int, max_per_category: int, display: int):
    """From a ranked pool, produce a deterministically-shuffled slice with
    at most `max_per_category` products per category_slug.

    Category cap is important: without it the multi-offer set skews toward
    the categories with the most inventory (phones, TVs) and the grid
    reads as monoculture. With it, one refresh might surface a fridge, a
    solar inverter, a kettle, and a laptop alongside the phones.
    """
    shuffled = list(pool)
    random.Random(bucket_seed).shuffle(shuffled)
    seen: dict[str, int] = defaultdict(int)
    selected = []
    for row in shuffled:
        product = row[0]  # (Product, min_price, offer_count)
        cat = product.category_slug or ""
        if seen[cat] >= max_per_category:
            continue
        selected.append(row)
        seen[cat] += 1
        if len(selected) >= display:
            break
    return selected


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
    # Ranking (for the pool — the top-N eligible products the rotation
    # picks from):
    #   1. offer_count DESC — showcase what the site is for (price comparison).
    #   2. clicks over the last 7d DESC — real-user signal on which listings
    #      matter, computed as a correlated scalar subquery so the main
    #      GROUP BY on Product.id stays clean (a JOIN through Click would
    #      multiply the min-price / offer-count aggregates).
    #   3. last_checked_at DESC — final tiebreak so untouched products don't
    #      tie forever.
    # Then _select_home_rows shuffles the pool with a 6h-bucket seed and
    # enforces category diversity so the grid rotates + reads mixed.
    # Pool filters: multi-offer (>=2) so we don't showcase single-offer
    # noindex'd pages, and image_url present so cards render properly.
    week_ago = datetime.utcnow() - timedelta(days=7)
    clicks_7d = (
        select(func.count(Click.id))
        .join(Listing, Listing.id == Click.listing_id)
        .where(Listing.product_id == Product.id)
        .where(Click.occurred_at >= week_ago)
        .correlate(Product)
        .scalar_subquery()
    )
    pool = session.exec(
        select(
            Product,
            func.min(Listing.price_kes).label("min_price"),
            func.count(Listing.id).label("offer_count"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.image_url.is_not(None))
        .group_by(Product.id)
        .having(func.count(Listing.id) >= 2)
        .order_by(
            func.count(Listing.id).desc(),
            clicks_7d.desc(),
            func.max(Listing.last_checked_at).desc(),
        )
        .limit(_HOME_POOL_SIZE)
    ).all()
    bucket = _time_bucket()
    rows = _select_home_rows(
        pool,
        bucket_seed=bucket,
        max_per_category=_HOME_MAX_PER_CATEGORY,
        display=_HOME_DISPLAY,
    )

    # Featured head-to-head — pick one product from the top slice of the
    # pool and fetch its cheapest N offers so the hero can render a real
    # side-by-side comparison rather than abstract stat chips.
    featured_row = _select_featured(pool, bucket, _FEATURED_POOL_SLICE)
    featured = None
    if featured_row is not None:
        product = featured_row[0]
        offers, savings_abs, savings_pct = _fetch_featured_offers(
            session, product.id, _FEATURED_MAX_OFFERS
        )
        # Only expose the featured block when the comparison is meaningful
        # (2+ offers). If the top-of-pool product got its second offer
        # delisted between the pool query and here, degrade to no hero
        # comparison rather than showing a 1-merchant "comparison".
        if len(offers) >= 2:
            featured = {
                "product": product,
                "offers": offers,          # list of (Listing, Merchant)
                "min_price": offers[0][0].price_kes,
                "savings_abs": savings_abs,
                "savings_pct": savings_pct,
                "total_offer_count": featured_row[2],  # from the pool aggregate
            }

    # Hero stats — cheap counts + one MAX().
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
            "featured": featured,
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
    # Always noindex the search page. The URL space is unbounded (any q= is a
    # valid page), and thin/empty-result variants would balloon the
    # "Discovered - not indexed" bucket. Standard SEO practice — Wikipedia,
    # Amazon, prisjakt all noindex their /search. Bare /search with no query
    # is functionally a duplicate of home, also noindex-worthy.
    return templates.TemplateResponse(
        request, "search.html", {"rows": rows, "q": q_clean, "noindex": True}
    )
