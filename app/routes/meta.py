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
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /out/\n"
        "Disallow: /alerts\n"
        f"Sitemap: {settings.base_url.rstrip('/')}/sitemap.xml\n"
    )


@router.get("/sitemap.xml")
def sitemap(session: Session = Depends(get_session)) -> Response:
    base = settings.base_url.rstrip("/")
    urls = [f"{base}/"]
    for slug in session.exec(select(Product.slug)).all():
        urls.append(f"{base}/p/{slug}")

    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        body.append(f"  <url><loc>{u}</loc></url>")
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")
