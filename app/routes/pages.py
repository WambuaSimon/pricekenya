import random
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from app.context import get_category_names, get_category_product_counts
from app.pricing import (
    GAP_MAX_RATIO,
    GAP_MIN_MERCHANTS,
    INSTALMENT_MARKERS,
    trim_price_outliers,
)
from app.templating import templates
from db.models import Click, Listing, Merchant, PriceHistory, Product
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
_FEATURED_MAX_OFFERS = 7    # offer rows shown in the hero head-to-head card

# "Where the gap is biggest" / "Dropped this week" sizing. The trust rules
# these sections lean on (GAP_MAX_RATIO, instalment markers, the outlier
# trim) live in app/pricing.py because the category grid applies them too.
_GAP_DISPLAY = 4
_DROP_DISPLAY = 6
_DROP_WINDOW_DAYS = 7


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


def _fetch_featured_offers(session: Session, product_id: int) -> list[tuple]:
    """Every in-stock offer for the featured product, cheapest first.

    Returns the full list rather than a top-N slice: the hero card states a
    min-to-max range and an "All N offers" link, and both have to describe
    the whole set. The template decides how many rows to draw. Products
    here carry a few dozen offers at most, so fetching all of them is
    cheaper than a second aggregate query.
    """
    return session.exec(
        select(Listing, Merchant)
        .join(Merchant, Merchant.id == Listing.merchant_id)
        .where(Listing.product_id == product_id)
        .where(*_trustworthy_offers())
        .order_by(Listing.price_kes.asc())
    ).all()


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


def _trustworthy_offers():
    """WHERE-clause fragments limiting a Listing query to offers we are
    willing to publish a savings claim against. See GAP_MAX_RATIO."""
    clauses = [Listing.in_stock.is_(True)]
    for marker in INSTALMENT_MARKERS:
        clauses.append(~func.lower(Listing.title_on_merchant).contains(marker))
    return clauses


def _fetch_price_gaps(session: Session, pool_ids: list[int], limit: int):
    """Products in the popular pool with the largest cheapest-to-dearest
    spread in shillings.

    Ranked by absolute saving rather than percentage: the section answers
    "where is the most money on the table", and a 40% gap on a 2,000 KSh
    kettle is not the answer. Restricted to pool_ids so the lede ("on
    things people actually buy") is true — the unrestricted query surfaces
    1.6M shilling TVs with three offers.

    Returns a list of dicts with the low, high, saving and the percentage
    the saving represents, which is also the progress-track fill.
    """
    if not pool_ids:
        return []
    q = select(
        Product,
        func.min(Listing.price_kes).label("low"),
        func.max(Listing.price_kes).label("high"),
        func.count(func.distinct(Listing.merchant_id)).label("shops"),
    ).join(Listing, Listing.product_id == Product.id)
    for clause in _trustworthy_offers():
        q = q.where(clause)
    rows = session.exec(
        q.where(Product.id.in_(pool_ids))
        .group_by(Product.id)
        .having(func.count(func.distinct(Listing.merchant_id)) >= GAP_MIN_MERCHANTS)
        .having(func.max(Listing.price_kes) <= GAP_MAX_RATIO * func.min(Listing.price_kes))
        .order_by((func.max(Listing.price_kes) - func.min(Listing.price_kes)).desc())
        .limit(limit)
    ).all()
    names = get_category_names()
    gaps = []
    for product, low, high, shops in rows:
        if not high or high <= low:
            continue
        saving = high - low
        gaps.append(
            {
                "product": product,
                "category": names.get(product.category_slug or "", ""),
                "low": low,
                "high": high,
                "saving": saving,
                "pct": round(saving / high * 100),
                "shops": shops,
            }
        )
    return gaps


def _fetch_price_drops(session: Session, pool_ids: list[int], limit: int):
    """Products whose cheapest live price is below what it was a week ago.

    "Was" is the cheapest price observed in the 8-to-6-day-old window
    rather than at an exact instant: scrape times drift, so pinning to
    `now - 7d` exactly would miss products that happened not to be checked
    that hour.

    Carries the same ratio guard as the gap cards. A week-over-week fall
    steeper than the guard allows is nearly always a matcher error rather
    than a real drop, and a wrong "-66%" badge is worse than no section.
    """
    if not pool_ids:
        return []
    now = datetime.utcnow()
    current = (
        select(
            Listing.product_id.label("pid"),
            func.min(Listing.price_kes).label("now_price"),
        )
        .where(*_trustworthy_offers())
        .group_by(Listing.product_id)
        .subquery()
    )
    previous = (
        select(
            Listing.product_id.label("pid"),
            func.min(PriceHistory.price_kes).label("was_price"),
        )
        .join(Listing, Listing.id == PriceHistory.listing_id)
        .where(
            PriceHistory.observed_at.between(
                now - timedelta(days=_DROP_WINDOW_DAYS + 1),
                now - timedelta(days=_DROP_WINDOW_DAYS - 1),
            )
        )
        .group_by(Listing.product_id)
        .subquery()
    )
    rows = session.exec(
        select(Product, current.c.now_price, previous.c.was_price)
        .join(current, current.c.pid == Product.id)
        .join(previous, previous.c.pid == Product.id)
        .where(Product.id.in_(pool_ids))
        .where(current.c.now_price < previous.c.was_price)
        .where(previous.c.was_price <= GAP_MAX_RATIO * current.c.now_price)
        .order_by(
            (
                (previous.c.was_price - current.c.now_price) / previous.c.was_price
            ).desc()
        )
        .limit(limit)
    ).all()
    drops = []
    for product, now_price, was_price in rows:
        if not was_price or was_price <= now_price:
            continue
        drops.append(
            {
                "product": product,
                "price": now_price,
                "was": was_price,
                "pct": round((was_price - now_price) / was_price * 100),
            }
        )
    return drops


def _humanize_ago(ts: datetime | None) -> str:
    """Short compact ago-string for the homepage stats chip. Naive UTC in,
    "12m ago" / "3h ago" / "2d ago" out. Only used for display — precision
    beyond the current bucket doesn't matter."""
    if ts is None:
        return "not yet checked"
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
        offers = trim_price_outliers(_fetch_featured_offers(session, product.id))
        # Only expose the featured block when the comparison is meaningful
        # (2+ offers). If the top-of-pool product got its second offer
        # delisted between the pool query and here, degrade to no hero
        # comparison rather than showing a 1-merchant "comparison".
        if len(offers) >= 2:
            cheapest_listing, cheapest_merchant = offers[0]
            dearest_listing, dearest_merchant = offers[-1]
            savings_abs = dearest_listing.price_kes - cheapest_listing.price_kes
            savings_pct = (
                round(savings_abs / dearest_listing.price_kes * 100)
                if dearest_listing.price_kes
                else None
            )
            featured = {
                "product": product,
                # Rows the card draws, vs the true totals behind the range
                # line and the "All N offers" link.
                "offers": offers[:_FEATURED_MAX_OFFERS],
                "total_offer_count": len(offers),
                "min_price": cheapest_listing.price_kes,
                "max_price": dearest_listing.price_kes,
                "cheapest_shop": cheapest_merchant.name,
                "dearest_shop": dearest_merchant.name,
                "savings_abs": savings_abs,
                "savings_pct": savings_pct,
            }

    pool_ids = [row[0].id for row in pool]
    gaps = _fetch_price_gaps(session, pool_ids, _GAP_DISPLAY)
    drops = _fetch_price_drops(session, pool_ids, _DROP_DISPLAY)

    # Hero stats — cheap counts + one MAX().
    product_count = session.exec(select(func.count(Product.id))).one()
    # Merchants we can actually send a shopper to today, not every merchant
    # that ever had a row. Counting all of them returned 54 while 11 were
    # deprecated merchants whose last scrape was 300-800h ago — and the hero
    # renders this next to "checked {{ last_updated_ago }}", so the unfiltered
    # figure made a false claim in the most prominent element on the site.
    # in_stock is the right filter rather than a freshness window: it needs no
    # new time constant, matches every other surface, and lands on the same
    # number (43) as "checked in the last 24h".
    merchant_count = session.exec(
        select(func.count(func.distinct(Listing.merchant_id)))
        .where(Listing.in_stock.is_(True))
    ).one()
    last_listing_check = session.exec(select(func.max(Listing.last_checked_at))).one()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "rows": rows,
            "featured": featured,
            "gaps": gaps,
            "drops": drops,
            "category_counts": get_category_product_counts(),
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
