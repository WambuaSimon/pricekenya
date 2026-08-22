"""SEO + ops + legal endpoints: robots.txt, sitemap.xml, healthz, /privacy, /terms."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from sqlmodel import Session, select

from app.config import settings
from app.templating import templates
from db.models import Product
from db.session import get_session

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

router = APIRouter()


@router.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


# Search-engine verification files that must live at the site root.
# These are one-shot tokens issued when we added the site to each service;
# safe to keep serving indefinitely — the search engines re-check on renewal.
_BING_SITE_AUTH = (
    '<?xml version="1.0"?>\n'
    "<users>\n"
    "\t<user>126891E5EB8D417E2E837EBB0E60F2BF</user>\n"
    "</users>"
)


@router.get("/BingSiteAuth.xml")
def bing_site_auth() -> Response:
    return Response(_BING_SITE_AUTH, media_type="application/xml")


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Browsers and crawlers probe /favicon.ico even when <link rel="icon">
    points elsewhere. Serve the multi-size ICO with a long CDN cache so
    Google's favicon-picker gets the raster it wants without a per-request
    hop to Render."""
    return FileResponse(
        _STATIC_DIR / "favicon.ico",
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400, s-maxage=604800"},
    )


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    """Kenya DPA privacy policy. Static template — no DB access."""
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/reviews-policy", response_class=HTMLResponse)
def reviews_policy(request: Request):
    """Public rules page for user reviews. Static template — no DB access.
    Linked from every review form so shoppers know the ground rules before
    submitting."""
    return templates.TemplateResponse(request, "reviews_policy.html", {})


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    """Terms of use. Static template — no DB access."""
    return templates.TemplateResponse(request, "terms.html", {})


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots() -> str:
    """Note: the "Block training in robots.txt" toggle in Cloudflare's
    Email/AI Audit UI would override this at the edge. We keep it OFF so
    the Sitemap directive below survives — Google needs it."""
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /out/\n"
        "Disallow: /alerts\n"
        "Disallow: /alerts/unsubscribe/\n"
        "Disallow: /watchlist\n"
        "Disallow: /admin\n"
        "Disallow: /internal/\n"
        f"Sitemap: {settings.base_url.rstrip('/')}/sitemap.xml\n"
    )


# How stale can the cached sitemap get before we regenerate on the next
# request? Google re-fetches a sitemap this size every 1-3 days, so a day
# of staleness is invisible to indexing. 24h caps the expensive
# product+listing join at one rebuild per day.
_SITEMAP_CACHE_TTL_HOURS = 24

# Response headers applied to every /sitemap.xml response, whether it
# came from cache or was just built. `s-maxage=21600` (6h) at the Cloudflare
# edge means keep-warm pings + Googlebot polls hit CF instead of Render/Neon
# for most of the day, so /sitemap.xml stops waking Neon every ~10 min.
_SITEMAP_HEADERS = {"Cache-Control": "public, max-age=21600, s-maxage=21600"}


def _non_empty_category_slugs(session: Session) -> list[str]:
    """Category slugs whose own subtree contains at least one Product.

    Kept in sitemap order (`Category.sort_order`). One pass up the parent
    chain rather than a descendant walk per category — 46 categories today,
    but the walk is O(n²) and this is O(n).
    """
    from sqlalchemy import func

    from db.models import Category

    cats = session.exec(select(Category).order_by(Category.sort_order)).all()
    parent_of = {c.id: c.parent_id for c in cats}
    slug_of = {c.id: c.slug for c in cats}
    id_of_slug = {c.slug: c.id for c in cats}

    direct = session.exec(
        select(Product.category_slug, func.count(Product.id))
        .group_by(Product.category_slug)
    ).all()

    non_empty: set[int] = set()
    for cat_slug, count in direct:
        if not count:
            continue
        # Mark the owning category and every ancestor above it. Products
        # attach to leaves; the structural parents aggregate them.
        node = id_of_slug.get(cat_slug)
        while node is not None and node not in non_empty:
            non_empty.add(node)
            node = parent_of.get(node)

    return [slug_of[c.id] for c in cats if c.id in non_empty]


def _build_sitemap_xml(session: Session) -> tuple[str, int]:
    """Build the full urlset. Returns (xml_body, url_count).

    Expensive: iterates every Product + joins Listing to get the freshest
    last_checked_at + serializes the whole thing into 1MB+ of XML. Only
    called from the /sitemap.xml route when the cache is missing or
    stale (see the SITEMAP_CACHE_TTL_HOURS constant)."""
    from datetime import datetime as _datetime
    from xml.sax.saxutils import escape as xml_escape

    from sqlalchemy import func

    from db.models import Listing

    base = settings.base_url.rstrip("/")

    # Google publicly ignores <changefreq>/<priority>; <lastmod> is the only
    # attribute that meaningfully affects re-crawl scheduling. Per-product
    # lastmod = max(Listing.last_checked_at) across its listings, so price/
    # stock refreshes signal a re-crawl. Site-wide max serves as lastmod for
    # the homepage and category pages — a safe over-estimate.
    site_lastmod: _datetime | None = session.exec(
        select(func.max(Listing.last_checked_at))
    ).one()

    def fmt(ts: _datetime | None) -> str | None:
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None

    site_lastmod_str = fmt(site_lastmod)

    entries: list[tuple[str, str | None, str | None]] = []
    entries.append((f"{base}/", site_lastmod_str, None))

    # Only categories that actually have something to show. `categories.py`
    # sets noindex when `total_rows == 0`, so emitting every slug
    # unconditionally advertised empty categories that then refused to be
    # indexed — 7 of 46 on 2026-08-22 (/c/toilets, /c/storage, /c/freezers,
    # /c/bathroom-fixtures, /c/water-dispensers-coolers, /c/printers-scanners,
    # /c/games-digital-cards). Same bug class as the product predicate below,
    # just smaller.
    #
    # A parent counts as non-empty when ANY descendant holds products —
    # non-leaf categories are structural and their landing pages aggregate
    # the subtree (see the Category model docstring), so `/c/electronics`
    # is a real page even though no product attaches to it directly.
    for slug in _non_empty_category_slugs(session):
        entries.append((f"{base}/c/{slug}", site_lastmod_str, None))

    # Prune to "sitemap-worthy" products. Emitting every Product row (7,471
    # on 2026-07-18) crowded the crawl budget: ~43% ended up as
    # "Discovered - currently not indexed" in Search Console because Google
    # decided crawling all 7k+ wasn't worth it. Filters:
    #  1. Require >= MIN_DISTINCT_MERCHANTS merchants with an IN-STOCK
    #     offer — the shared rule in app/indexing.py, the same one
    #     product.html uses to decide `noindex`. A single-offer page is
    #     functionally a merchant redirect, not a comparison.
    #  2. Require Product.image_url — no image = thin content = Google
    #     rejects at "Crawled - not indexed".
    #  3. Require max(last_checked_at) within FRESHNESS_DAYS — products
    #     whose every listing hasn't been re-verified in months are almost
    #     certainly delisted upstream.
    #
    # The in-stock restriction is the fix for the 2026-08-22 bug: this
    # query used to count ALL listings while the page counted only in-stock
    # ones, so 1,175 of the 2,504 product URLs advertised here (46.9%)
    # served `noindex` when Google fetched them. Filtering the join (rather
    # than adding another HAVING) is what makes the distinct-merchant count
    # see live offers only — see indexable_having()'s docstring.
    #
    # Sub-threshold products remain reachable via category pages and search;
    # they just don't get promoted to Google via the sitemap.
    from datetime import timedelta as _timedelta

    from app.indexing import FRESHNESS_DAYS, indexable_having

    freshness_cutoff = _datetime.utcnow() - _timedelta(days=FRESHNESS_DAYS)

    product_rows = session.exec(
        select(
            Product.slug,
            Product.image_url,
            func.max(Listing.last_checked_at).label("lastmod"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.image_url.is_not(None))
        .where(Listing.in_stock.is_(True))
        .group_by(Product.id)
        .having(indexable_having())
        .having(func.max(Listing.last_checked_at) >= freshness_cutoff)
        .order_by(func.max(Listing.last_checked_at).desc())
    ).all()
    for slug, image_url, lastmod in product_rows:
        entries.append((f"{base}/p/{slug}", fmt(lastmod), image_url))

    entries.append((f"{base}/privacy", None, None))
    entries.append((f"{base}/terms", None, None))

    parts_out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]
    for loc, lastmod, image_url in entries:
        row = [f"<loc>{xml_escape(loc)}</loc>"]
        if lastmod:
            row.append(f"<lastmod>{lastmod}</lastmod>")
        if image_url:
            row.append(
                f"<image:image><image:loc>{xml_escape(image_url)}</image:loc></image:image>"
            )
        parts_out.append("  <url>" + "".join(row) + "</url>")
    parts_out.append("</urlset>")
    return "\n".join(parts_out), len(entries)


@router.get("/sitemap.xml")
def sitemap(session: Session = Depends(get_session)) -> Response:
    """Cache-first sitemap. First request in every _SITEMAP_CACHE_TTL_HOURS
    window pays the ~5k-URL build cost + writes the result to
    CachedSitemap(id=1); every subsequent request in that window is a
    single-row SELECT plus a 1MB Response. The Cloudflare edge cache
    (`s-maxage=3600`) makes the middle layer of the sandwich even cheaper.

    On cold DB (no cached row yet) we build inline and cache the result.
    Deliberately no admin auth on the fallback build — it's the same route
    Googlebot hits."""
    from datetime import datetime as _datetime
    from datetime import timedelta as _timedelta

    from db.models import CachedSitemap

    now = _datetime.utcnow()
    ttl = _timedelta(hours=_SITEMAP_CACHE_TTL_HOURS)

    cached = session.get(CachedSitemap, 1)
    if cached and (now - cached.generated_at) < ttl:
        return Response(cached.body, media_type="application/xml", headers=_SITEMAP_HEADERS)

    body, url_count = _build_sitemap_xml(session)

    if cached:
        cached.body = body
        cached.generated_at = now
        cached.url_count = url_count
        session.add(cached)
    else:
        session.add(CachedSitemap(id=1, body=body, generated_at=now, url_count=url_count))
    session.commit()

    return Response(body, media_type="application/xml", headers=_SITEMAP_HEADERS)
