from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, func, select

from app.config import settings
from app.indexing import offers_are_indexable
from app.pricing import instalment_exclusions, trim_price_outliers
from app.templating import templates
from db.models import Click, Listing, Merchant, PriceHistory, Product, ProductRedirect, Review
from db.session import get_session

router = APIRouter()


def _affiliate_url(merchant: Merchant, raw_url: str) -> str:
    if merchant.slug == "jumia-ke" and settings.jumia_affiliate_id:
        sep = "&" if "?" in raw_url else "?"
        return f"{raw_url}{sep}utm_source=pricekenya&aff={settings.jumia_affiliate_id}"
    return raw_url


# Weekly price chart. 13 weeks is the 90-day frame the section was
# originally specced at; the bar count is derived from the history actually
# on hand and only reaches 13 once there are 90 days of it. Rendering a
# fixed 13 against 8 weeks of data draws five empty slots, which reads as
# "we lost your data" rather than "we started recording in July".
_CHART_MAX_WEEKS = 13
_CHART_MIN_WEEKS = 2


def _weekly_price_series(rows, max_weeks: int = _CHART_MAX_WEEKS):
    """Reshape raw (observed_at, price) history into best-price-per-week.

    This is the reshape the disabled canvas sparkline in product.html was
    waiting on. The old block plotted every observation from every listing
    on one line, so a product with 11 merchants drew 11 interleaved price
    levels and read as noise. One bar per week, each the cheapest price
    anyone listed that week, answers the question the section asks: is this
    getting cheaper or not.

    Weeks are counted back from the most recent observation, not from now,
    so a product whose scraping paused does not grow a run of empty bars on
    the right. Weeks with no observation are omitted rather than zero-filled
    or carried forward: a flat carried-forward bar asserts a price nobody
    listed.

    Returns [] when there is too little history to say anything.
    """
    if not rows:
        return []
    latest = max(observed_at for observed_at, _ in rows)
    buckets: dict[int, float] = {}
    for observed_at, price in rows:
        index = (latest - observed_at).days // 7
        if index >= max_weeks:
            continue
        value = float(price)
        if index not in buckets or value < buckets[index]:
            buckets[index] = value
    if len(buckets) < _CHART_MIN_WEEKS:
        return []

    peak = max(buckets.values())
    series = []
    # Reverse so the oldest week is first and the latest bar sits at the right.
    for index in sorted(buckets, reverse=True):
        price = buckets[index]
        week_start = latest - timedelta(days=index * 7)
        series.append(
            {
                "price": price,
                # Floor at 4% so a genuinely cheap week is still a visible
                # bar rather than an invisible sliver.
                "height": max(4, round(price / peak * 100)) if peak else 0,
                "label": week_start.strftime("%-d %b"),
                "is_latest": index == 0,
            }
        )
    return series


# Spec strip. Labels and units for the spec keys the matcher populates;
# anything not listed here is skipped rather than shown with a raw key
# name like "capacity_ah".
_SPEC_LABELS: dict[str, tuple[str, str]] = {
    "storage_gb": ("Storage", "GB"),
    "ram_gb": ("RAM", "GB"),
    "screen_inches": ("Screen", " inch"),
    "resolution": ("Resolution", ""),
    "capacity_liters": ("Capacity", "L"),
    "capacity_kg": ("Capacity", "kg"),
    "capacity_ah": ("Capacity", "Ah"),
    "watts": ("Power", "W"),
    "load_type": ("Load", ""),
    "condition": ("Condition", ""),
}
_SPEC_STRIP_MAX = 4
_SPEC_STRIP_MIN = 2


def _spec_strip(product) -> list[dict]:
    """Present spec keys for the strip above the Where-to-buy table.

    Renders only keys that exist, caps at four, and returns [] below two.
    A fixed four-up grid draws blank slots for most of the catalog: only
    ~44% of products carry four or more keys and ~8% carry none. The
    reference shows four because the A17 happens to have four.
    """
    specs = getattr(product, "specs", None) or {}
    if not isinstance(specs, dict):
        return []
    items = []
    for key, (label, unit) in _SPEC_LABELS.items():
        if len(items) >= _SPEC_STRIP_MAX:
            break
        value = specs.get(key)
        if value in (None, "", "unknown"):
            continue
        # Spec numbers arrive as floats from JSON; 128.0 should read "128GB".
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        text = f"{value}{unit}" if unit else str(value).title()
        items.append({"label": label, "value": text})
    return items if len(items) >= _SPEC_STRIP_MIN else []


@router.get("/p/{slug}", response_class=HTMLResponse)
def product_detail(slug: str, request: Request, session: Session = Depends(get_session)):
    product = session.exec(select(Product).where(Product.slug == slug)).first()
    if not product:
        # Before 404'ing, check if this slug was merged into another product
        # (via scripts/coarsen_phones_backfill or similar). 301 preserves
        # any Google link equity accrued to the old URL. See OPERATIONS.md §8h
        # / ProductRedirect model for the outage log.
        redirect = session.exec(
            select(ProductRedirect).where(ProductRedirect.old_slug == slug)
        ).first()
        if redirect:
            return RedirectResponse(url=f"/p/{redirect.new_slug}", status_code=301)
        raise HTTPException(status_code=404)

    # Only show in-stock offers. Merchants (esp. Shopify stores) sometimes
    # keep sold-out products listed with placeholder prices — surfacing those
    # sends shoppers to dead pages and erodes trust. Template already handles
    # offers=[] with a "No offers right now." message; sitemap already
    # filters by MIN_OFFERS + FRESHNESS_DAYS so we don't index empty pages.
    #
    # Instalment listings are excluded and price outliers trimmed for the
    # same reason the homepage does it: this page states a spread ("KSh
    # 11,000 apart") and a "cheapest shop" recommendation, and one bad row
    # rewrites both. The two surfaces have to agree, or the hero links to a
    # page contradicting it. See app/pricing.py.
    listings = session.exec(
        select(Listing, Merchant)
        .join(Merchant, Merchant.id == Listing.merchant_id)
        .where(Listing.product_id == product.id)
        .where(Listing.in_stock.is_(True))
        .where(*instalment_exclusions(Listing))
        .order_by(Listing.price_kes.asc())
    ).all()
    listings = trim_price_outliers(listings)

    offers = []
    for listing, merchant in listings:
        offers.append(
            {
                "merchant": merchant,
                "listing": listing,
                "out_url": f"/out/{listing.id}",
            }
        )

    # Weekly price chart. Only the two columns the reshape needs, not whole
    # PriceHistory rows — a popular product carries several hundred
    # observations across its listings and none of the other fields are used.
    listing_ids = [listing.id for listing, _ in listings]
    history_rows = []
    if listing_ids:
        history_rows = session.exec(
            select(PriceHistory.observed_at, PriceHistory.price_kes)
            .where(PriceHistory.listing_id.in_(listing_ids))
            .where(
                PriceHistory.observed_at
                >= datetime.utcnow() - timedelta(weeks=_CHART_MAX_WEEKS)
            )
            .order_by(PriceHistory.observed_at.asc())
        ).all()
    price_series = _weekly_price_series(history_rows)

    min_price = offers[0]["listing"].price_kes if offers else None
    max_price = offers[-1]["listing"].price_kes if offers else None
    # Freshest listing check across all in-stock offers. Rendered in the
    # meta description ("updated 28 Jul 2026") and as a visible on-page
    # line so both users and Googlebot see a recency signal.
    last_updated = max(
        (o["listing"].last_checked_at for o in offers if o["listing"].last_checked_at),
        default=None,
    )
    # When every merchant lists the same price, "Best price" is misleading —
    # nothing is "best" if the value equals every other value. The template
    # uses these to hide the badge, background highlight, and emerald price
    # color, and to swap "best price across N merchants" for "same price at
    # N merchants" in the subtitle.
    best_price_count = (
        sum(1 for o in offers if o["listing"].price_kes == min_price)
        if offers and min_price is not None
        else 0
    )
    all_tied = bool(offers) and best_price_count == len(offers)

    # Related: same category, ordered by absolute price proximity to this
    # product's best price. Price-proximity is the axis shoppers actually
    # compare on — same-brand alternatives feel repetitive on a
    # price-comparison site. Shape matches _product_grid.html: (product,
    # min_price, offer_count).
    related: list = []
    if min_price is not None:
        related = session.exec(
            select(
                Product,
                func.min(Listing.price_kes).label("min_price"),
                func.count(Listing.id).label("offer_count"),
            )
            .join(Listing, Listing.product_id == Product.id)
            .where(Product.category_slug == product.category_slug)
            .where(Product.id != product.id)
            .where(Listing.in_stock.is_(True))
            .group_by(Product.id)
            .order_by(func.abs(func.min(Listing.price_kes) - float(min_price)).asc())
            .limit(6)
        ).all()

    # Verified reviews only, and never rows the admin has hidden.
    # Unverified rows are pending magic-link click and never render
    # publicly. Aggregate rating is computed here so template + JSON-LD
    # share the same numbers.
    reviews = session.exec(
        select(Review)
        .where(
            Review.product_id == product.id,
            Review.verified_at.is_not(None),
            Review.hidden_at.is_(None),
        )
        .order_by(Review.created_at.desc())
    ).all()
    review_count = len(reviews)
    avg_rating = (
        round(sum(r.rating for r in reviews) / review_count, 1)
        if review_count
        else None
    )

    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "offers": offers,
            # Computed here rather than counted in the template so the
            # sitemap and the page's robots meta read the same rule from
            # app/indexing.py. They disagreed until 2026-08-22 and nothing
            # caught it — see that module's docstring.
            "is_indexable": offers_are_indexable(offers),
            "min_price": min_price,
            "max_price": max_price,
            "last_updated": last_updated,
            "best_price_count": best_price_count,
            "all_tied": all_tied,
            "related": related,
            "reviews": reviews,
            "review_count": review_count,
            "avg_rating": avg_rating,
            "price_series": price_series,
            "spec_items": _spec_strip(product),
        },
    )


@router.get("/out/{listing_id}")
def out(listing_id: int, session: Session = Depends(get_session)):
    row = session.exec(
        select(Listing, Merchant)
        .join(Merchant, Merchant.id == Listing.merchant_id)
        .where(Listing.id == listing_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404)
    listing, merchant = row
    # Log the click for interest-signal + eventual revenue attribution. No
    # PII: only the listing id and timestamp. See Privacy Policy §6.
    session.add(Click(listing_id=listing.id))
    session.commit()
    return RedirectResponse(url=_affiliate_url(merchant, listing.url), status_code=302)
