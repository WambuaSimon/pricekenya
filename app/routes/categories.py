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

from app.facets import MIN_MERCHANTS_TO_COMPARE, Facet, facets_for
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


def _facet_counts(
    session: Session, category_slugs: list[str], facets: list[Facet]
) -> dict[str, dict[str, int]]:
    """Product count per enum facet value, as `{facet_key: {value: count}}`.

    Counted under the same base restrictions as the grid (this category
    tree, in-stock listings only) but deliberately NOT under the currently
    active filters, matching _available_values above. The sidebar is a map
    of where you could go, so the Samsung count should not drop to zero
    just because you currently have Xiaomi ticked.

    One grouped query per enum facet, same as _available_values.
    """
    out: dict[str, dict[str, int]] = {}
    for f in facets:
        if f.kind != "enum":
            continue
        if f.source == "brand":
            expr = Product.brand
        elif key := _spec_key(f.source):
            expr = _spec_as_text(key)
        else:
            continue
        rows = session.exec(
            select(expr, func.count(func.distinct(Product.id)))
            .join(Listing, Listing.product_id == Product.id)
            .where(Product.category_slug.in_(category_slugs))
            .where(Listing.in_stock.is_(True))
            .where(expr.is_not(None))
            .group_by(expr)
        ).all()
        counts: dict[str, int] = {}
        for value, n in rows:
            if value in (None, "", "null"):
                continue
            # _available_values trims integer-valued specs to "128"; match
            # that spelling so template lookups line up.
            label = str(value)
            if label.endswith(".0"):
                label = label[:-2]
            counts[label] = n
        out[f.key] = counts
    return out


def _ancestors(session: Session, category: Category) -> list[Category]:
    """Parent chain above `category`, outermost first, for the breadcrumb."""
    chain: list[Category] = []
    node = category
    seen: set[int] = set()
    while node.parent_id is not None and node.parent_id not in seen:
        seen.add(node.parent_id)
        parent = session.get(Category, node.parent_id)
        if parent is None:
            break
        chain.append(parent)
        node = parent
    return list(reversed(chain))


# Grid sort options. Keys are what appears in ?sort=; the default is the
# historical ordering (most shops first, then freshest).
SORTS = {
    "shops": "Most shops",
    "gap": "Biggest gap",
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
}
DEFAULT_SORT = "shops"


PAGE_SIZE = 48


@router.get("/c/{slug}", response_class=HTMLResponse)
def category_page(
    slug: str,
    request: Request,
    page: int = 1,
    sort: str = DEFAULT_SORT,
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

    if sort not in SORTS:
        sort = DEFAULT_SORT

    facets = facets_for(slug)
    active = _parse_filters(request, facets)
    available = _available_values(session, slugs, facets)
    facet_counts = _facet_counts(session, slugs, facets)
    # _available_values reads every distinct value in the tree, including
    # ones whose products have no live listing. The grid is in-stock-only,
    # so those options would filter to an empty grid and render with no
    # count beside them. Keep only values the counts query actually saw,
    # preserving _available_values' numeric ordering.
    available = {
        key: [v for v in values if facet_counts.get(key, {}).get(v)]
        for key, values in available.items()
    }

    # Base query: Product joined to Listing so we can aggregate min_price +
    # offer_count. Filters get layered in as WHERE (enum) or HAVING (range
    # on aggregate) clauses.
    #
    # The in_stock restriction is not optional and not a user facet. Until
    # 2026-08-25 this aggregated over EVERY listing, so a category card
    # advertised the cheapest price on record even when that price came from
    # a merchant we stopped scraping weeks ago. Measured on prod:
    # 1,793 products showed a price from a deprecated merchant, and 1,477 of
    # those had no live offer behind them at all. The shopper saw
    # "KSh 18,500 · 3 offers", clicked, and got a higher price or "No offers
    # right now" — because product_detail (products.py) filters on in_stock
    # and this did not.
    #
    # Same bug class as the sitemap/noindex mismatch fixed in #22: two
    # surfaces answering "what offers exist" differently, each plausible on
    # its own. Every user-facing surface now agrees: this grid, the home grid
    # (pages.py), the product page (products.py) and the sitemap (meta.py)
    # all count only in-stock listings.
    # Cards count DISTINCT MERCHANTS, not listings. The label reads "N
    # shops", and a merchant carrying the same product under two SKUs was
    # inflating that to "2 shops" from one seller. Same definition as
    # compared_count below and as indexing.MIN_DISTINCT_MERCHANTS.
    q = (
        select(
            Product,
            func.min(Listing.price_kes).label("min_price"),
            func.count(func.distinct(Listing.merchant_id)).label("shop_count"),
            func.max(Listing.price_kes).label("max_price"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
        .where(Listing.in_stock.is_(True))
    )

    for f in facets:
        val = active.get(f.key)
        if val is None:
            continue
        if f.kind == "enum":
            q = _apply_enum(q, f, val)  # type: ignore[arg-type]
        # NOTE: there is deliberately no `in_stock` branch here any more. The
        # base query above always restricts to in-stock listings, so the old
        # facet could only ever be a no-op. A control that visibly does
        # nothing is worse than no control, so the facet itself is gone from
        # app/facets.py too. A bookmarked `?in_stock=1` URL is simply ignored.

    q = q.group_by(Product.id)

    # HAVING clauses for range filters that operate on aggregates.
    price_max = active.get("price_max")
    if isinstance(price_max, str) and price_max.isdigit():
        q = q.having(func.min(Listing.price_kes) <= int(price_max))

    # "Only comparable products" — the same rule as the Comparable stat.
    # Deliberately NOT the sitemap's rule any more: indexing dropped to a
    # single merchant on 2026-09-09, but you still cannot compare prices
    # against one seller. See app/facets.py.
    if active.get("comparable"):
        q = q.having(
            func.count(func.distinct(Listing.merchant_id)) >= MIN_MERCHANTS_TO_COMPARE
        )

    # Ordering: multi-offer products first, then freshest. A comparison
    # site's value prop is "see all merchants for this product side by
    # side" — putting single-offer products at the top (which the prior
    # `created_at DESC` sort did) buried the actually-shoppable pages
    # under the newest-scraped singletons. Reversed on 2026-08-05 after
    # the phones-category audit showed the top of /c/phones was
    # dominated by 1-offer products, which is exactly the failure users
    # see. Ties within an offer count fall back to freshness so
    # newly-scraped products still surface within their tier.
    #
    # The sort control added with the 2026-08 revamp layers on top of this:
    # `shops` is the historical default described above, and the others are
    # opt-in via ?sort=. Every branch keeps a deterministic final tiebreak so
    # pagination can't show the same product on two pages.
    if sort == "gap":
        order = [(func.max(Listing.price_kes) - func.min(Listing.price_kes)).desc()]
    elif sort == "price_asc":
        order = [func.min(Listing.price_kes).asc()]
    elif sort == "price_desc":
        order = [func.min(Listing.price_kes).desc()]
    else:
        order = [
            func.count(func.distinct(Listing.merchant_id)).desc(),
            Product.created_at.desc(),
        ]
    q = q.order_by(*order, func.max(Listing.last_checked_at).desc(), Product.id.asc())

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
    #
    # These carry the same in_stock restriction as the grid above, and they
    # have to: the grid now shows only products with a live offer, so a
    # "Products" figure counting the rest would contradict the thing sitting
    # directly beneath it. Same for "Shops" — a merchant with nothing in
    # stock is not a shop you can buy from today.
    counts = session.exec(
        select(
            func.count(func.distinct(Product.id)),
            func.count(func.distinct(Listing.merchant_id)),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
        .where(Listing.in_stock.is_(True))
    ).one()
    product_count, merchant_count = counts

    # "Compared" = products with LIVE listings from MIN_MERCHANTS_TO_COMPARE+
    # distinct merchants. This used to be the same rule as app/indexing.py's
    # MIN_DISTINCT_MERCHANTS, so the figure also equalled the set the
    # sitemap advertised. That stopped being true on 2026-09-09 when
    # indexing dropped to a single merchant: a one-seller page is worth
    # serving to Google, but there is nothing on it to compare. This stat
    # keeps the stricter rule because it is a claim about shopping, not
    # about indexing.
    compared_subq = (
        select(Product.id)
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.category_slug.in_(slugs))
        .where(Listing.in_stock.is_(True))
        .group_by(Product.id)
        .having(
            func.count(func.distinct(Listing.merchant_id)) >= MIN_MERCHANTS_TO_COMPARE
        )
        .subquery()
    )
    compared_count = session.exec(
        select(func.count()).select_from(compared_subq)
    ).one() or 0

    # Noindex category views that shouldn't compete with the base URL:
    #   - Any filter active (?brand=…&storage=…) — filtered facet views
    #     produce combinatorial URL space, textbook noindex territory
    #   - Zero products for the current view — thin/empty page
    # Base /c/<slug> with results stays indexed — that's where the
    # category-level SEO value lives.
    #
    #   - A non-default ?sort= — it reorders the same product set, so it is
    #     duplicate content against the base URL for the same reason a facet
    #     is. Treated exactly like a filter, including for the canonical.
    #
    # `page > 1` was in this list until 2026-08-22 and is deliberately not
    # any more. Paginated views were emitting BOTH `noindex` and a canonical
    # pointing at a different URL (page 1, because base.html strips the query
    # string). Google's own guidance calls that pair contradictory — the
    # noindex can propagate to the canonical target, which here is the page
    # we most want indexed. It also stranded products that only appear on
    # page 2+: `noindex,follow` still allows crawling, but a noindexed page
    # is a weak path and those products were reachable no other way.
    #
    # Standard pagination handling instead: let page 2+ be indexable with a
    # self-referential canonical (see `canonical_url` below). Thin-content
    # risk is low — each page carries PAGE_SIZE distinct products.
    noindex = bool(active) or total_rows == 0 or sort != DEFAULT_SORT

    # Self-referential canonical for paginated views, so the page no longer
    # claims to be a different URL. Filtered and sorted views keep pointing at
    # the clean base URL: they're noindex either way, and self-canonicalising
    # them would mint a canonical for every facet/sort combination. Gating on
    # the default sort also keeps us out of the contradictory pair above —
    # without it, /c/x?sort=gap&page=2 would be noindex while canonicalising
    # to ?page=2, a third URL that is neither itself nor the base.
    canonical_url = str(request.url).split("?")[0]
    if page > 1 and not active and sort == DEFAULT_SORT:
        canonical_url = f"{canonical_url}?page={page}"
    return templates.TemplateResponse(
        request,
        "category.html",
        {
            "category": category,
            "ancestors": _ancestors(session, category),
            "children": children,
            "rows": rows,
            "product_count": product_count or 0,
            "merchant_count": merchant_count or 0,
            "compared_count": compared_count,
            "facets": facets,
            "active_filters": active,
            "available_values": available,
            "facet_counts": facet_counts,
            "sort": sort,
            "sorts": SORTS,
            "page": page,
            "total_pages": total_pages,
            "page_size": PAGE_SIZE,
            "total_matching": total_rows,
            "noindex": noindex,
            "canonical_url": canonical_url,
        },
    )
