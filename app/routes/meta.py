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
        f"Sitemap: {settings.base_url.rstrip('/')}/sitemap.xml\n"
    )


# How stale can the cached sitemap get before we regenerate on the next
# request? Six hours is a very safe over-estimate: Google re-fetches a
# sitemap this size every 1-3 days, so six hours of staleness is invisible
# to indexing. Meanwhile it caps how often we hit the expensive
# product+listing join on a Render Starter dyno.
_SITEMAP_CACHE_TTL_HOURS = 6

# Response headers applied to every /sitemap.xml response, whether it
# came from cache or was just built. `s-maxage` targets Cloudflare's edge.
_SITEMAP_HEADERS = {"Cache-Control": "public, max-age=3600, s-maxage=3600"}


def _build_sitemap_xml(session: Session) -> tuple[str, int]:
    """Build the full urlset. Returns (xml_body, url_count).

    Expensive: iterates every Product + joins Listing to get the freshest
    last_checked_at + serializes the whole thing into 1MB+ of XML. Only
    called from the /sitemap.xml route when the cache is missing or
    stale (see the SITEMAP_CACHE_TTL_HOURS constant)."""
    from datetime import datetime as _datetime
    from xml.sax.saxutils import escape as xml_escape

    from sqlalchemy import func

    from db.models import Category, Listing

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
    for slug in session.exec(select(Category.slug).order_by(Category.sort_order)).all():
        entries.append((f"{base}/c/{slug}", site_lastmod_str, None))

    # Prune to "sitemap-worthy" products. Emitting every Product row (7,471
    # on 2026-07-18) crowded the crawl budget: ~43% ended up as
    # "Discovered - currently not indexed" in Search Console because Google
    # decided crawling all 7k+ wasn't worth it. Filters:
    #  1. Require >= MIN_OFFERS live merchant offers. A single-offer page
    #     is functionally a merchant redirect, not a comparison — Google
    #     correctly deprioritises them. Local audit: 73% of products
    #     (5,431 of 7,461) sit at 1 offer, so raising the bar to 2 cuts
    #     the sitemap by ~73% and concentrates crawl budget on the
    #     comparison pages that actually justify indexing.
    #  2. Require Product.image_url — no image = thin content = Google
    #     rejects at "Crawled - not indexed".
    #  3. Require max(last_checked_at) within FRESHNESS_DAYS — products
    #     whose every listing hasn't been re-verified in months are almost
    #     certainly delisted upstream.
    #
    # Single-offer products remain reachable via category pages and search;
    # they just don't get promoted to Google via the sitemap.
    from datetime import timedelta as _timedelta

    MIN_OFFERS = 2
    FRESHNESS_DAYS = 60
    freshness_cutoff = _datetime.utcnow() - _timedelta(days=FRESHNESS_DAYS)

    product_rows = session.exec(
        select(
            Product.slug,
            Product.image_url,
            func.max(Listing.last_checked_at).label("lastmod"),
        )
        .join(Listing, Listing.product_id == Product.id)
        .where(Product.image_url.is_not(None))
        .group_by(Product.id)
        .having(func.count(Listing.id) >= MIN_OFFERS)
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
