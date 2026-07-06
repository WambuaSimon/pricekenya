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
        f"Sitemap: {settings.base_url.rstrip('/')}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
def sitemap(session: Session = Depends(get_session)) -> Response:
    from xml.sax.saxutils import escape as xml_escape

    from db.models import Category

    base = settings.base_url.rstrip("/")

    # ordered: high-value + evergreen first (root + categories), then long-tail
    # (products). Static legal pages last — indexable but not priority-boosted.
    entries: list[tuple[str, str, str]] = []  # (loc, changefreq, priority)
    entries.append((f"{base}/", "daily", "1.0"))
    for slug in session.exec(select(Category.slug).order_by(Category.sort_order)).all():
        entries.append((f"{base}/c/{slug}", "daily", "0.8"))
    for slug in session.exec(select(Product.slug)).all():
        entries.append((f"{base}/p/{slug}", "weekly", "0.6"))
    entries.append((f"{base}/privacy", "yearly", "0.2"))
    entries.append((f"{base}/terms", "yearly", "0.2"))

    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, freq, prio in entries:
        body.append(
            "  <url>"
            f"<loc>{xml_escape(loc)}</loc>"
            f"<changefreq>{freq}</changefreq>"
            f"<priority>{prio}</priority>"
            "</url>"
        )
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")
