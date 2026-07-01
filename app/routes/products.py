from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.config import settings
from app.templating import templates
from db.models import Listing, Merchant, PriceHistory, Product
from db.session import get_session

router = APIRouter()


def _affiliate_url(merchant: Merchant, raw_url: str) -> str:
    if merchant.slug == "jumia-ke" and settings.jumia_affiliate_id:
        sep = "&" if "?" in raw_url else "?"
        return f"{raw_url}{sep}utm_source=pricekenya&aff={settings.jumia_affiliate_id}"
    return raw_url


@router.get("/p/{slug}", response_class=HTMLResponse)
def product_detail(slug: str, request: Request, session: Session = Depends(get_session)):
    product = session.exec(select(Product).where(Product.slug == slug)).first()
    if not product:
        raise HTTPException(status_code=404)

    listings = session.exec(
        select(Listing, Merchant)
        .join(Merchant, Merchant.id == Listing.merchant_id)
        .where(Listing.product_id == product.id)
        .order_by(Listing.price_kes.asc())
    ).all()

    offers = []
    for listing, merchant in listings:
        offers.append(
            {
                "merchant": merchant,
                "listing": listing,
                "out_url": f"/out/{listing.id}",
            }
        )

    # Aggregate history across all listings for a single sparkline.
    listing_ids = [l.id for l, _ in listings]
    history = []
    if listing_ids:
        history = session.exec(
            select(PriceHistory)
            .where(PriceHistory.listing_id.in_(listing_ids))
            .order_by(PriceHistory.observed_at.asc())
        ).all()

    return templates.TemplateResponse(
        request,
        "product.html",
        {
            "product": product,
            "offers": offers,
            "min_price": offers[0]["listing"].price_kes if offers else None,
            "history": [
                {"t": h.observed_at.isoformat(), "p": float(h.price_kes)} for h in history
            ],
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
    # v1: log the click for analytics + revenue attribution.
    return RedirectResponse(url=_affiliate_url(merchant, listing.url), status_code=302)
