"""SEO + ops + legal endpoints: robots.txt, sitemap.xml, healthz, /privacy, /terms."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlmodel import Session, select

from app.config import settings
from app.templating import templates
from db.models import Product
from db.session import get_session

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


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    """Kenya DPA privacy policy. Static template — no DB access."""
    return templates.TemplateResponse(request, "privacy.html", {})


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


@router.get("/sitemap.xml")
def sitemap(session: Session = Depends(get_session)) -> Response:
    from datetime import datetime
    from xml.sax.saxutils import escape as xml_escape

    from sqlalchemy import func

    from db.models import Category, Listing

    base = settings.base_url.rstrip("/")

    # Google publicly ignores <changefreq>/<priority>; <lastmod> is the only
    # attribute that meaningfully affects re-crawl scheduling. Per-product
    # lastmod = max(Listing.last_checked_at) across its listings, so price/
    # stock refreshes signal a re-crawl. Site-wide max serves as lastmod for
    # the homepage and category pages — a safe over-estimate (worst case
    # Google re-crawls category pages slightly more often than needed).
    site_lastmod: datetime | None = session.exec(select(func.max(Listing.last_checked_at))).one()

    def fmt(ts: datetime | None) -> str | None:
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None

    site_lastmod_str = fmt(site_lastmod)

    # (loc, lastmod, image_url). image_url only set for product URLs.
    entries: list[tuple[str, str | None, str | None]] = []
    entries.append((f"{base}/", site_lastmod_str, None))
    for slug in session.exec(select(Category.slug).order_by(Category.sort_order)).all():
        entries.append((f"{base}/c/{slug}", site_lastmod_str, None))

    # One query for all products with their freshest listing timestamp and image.
    # Ordered freshest-first so Google prioritizes recently-changed pages when
    # it only reads part of the sitemap.
    product_rows = session.exec(
        select(
            Product.slug,
            Product.image_url,
            func.coalesce(func.max(Listing.last_checked_at), Product.created_at).label("lastmod"),
        )
        .join(Listing, Listing.product_id == Product.id, isouter=True)
        .group_by(Product.id)
        .order_by(func.coalesce(func.max(Listing.last_checked_at), Product.created_at).desc())
    ).all()
    for slug, image_url, lastmod in product_rows:
        entries.append((f"{base}/p/{slug}", fmt(lastmod), image_url))

    entries.append((f"{base}/privacy", None, None))
    entries.append((f"{base}/terms", None, None))

    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
        ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]
    for loc, lastmod, image_url in entries:
        parts = [f"<loc>{xml_escape(loc)}</loc>"]
        if lastmod:
            parts.append(f"<lastmod>{lastmod}</lastmod>")
        if image_url:
            parts.append(
                f"<image:image><image:loc>{xml_escape(image_url)}</image:loc></image:image>"
            )
        body.append("  <url>" + "".join(parts) + "</url>")
    body.append("</urlset>")
    # Cache at Cloudflare's edge for an hour so Googlebot never hits a cold
    # Render container while the sitemap query rebuilds. s-maxage targets
    # the CDN; browsers still respect max-age for their own cache. Search
    # engines re-fetch on their own schedule (Google every 1–3 days for a
    # site our size), so an hour of staleness is invisible to indexing.
    return Response(
        "\n".join(body),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600, s-maxage=3600"},
    )
