from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from alerts.tokens import (
    make_watchlist_cookie,
    verify_unsubscribe_token,
    verify_watchlist_cookie,
)
from app.templating import templates
from db.models import Alert, Listing, Product
from db.session import get_session

router = APIRouter()

# 1-year expiry: watchlist should feel persistent, but not eternal.
_WATCHLIST_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


@router.post("/alerts", response_class=HTMLResponse)
def create_alert(
    request: Request,
    product_id: int = Form(...),
    email: str = Form(...),
    target_price_kes: str = Form(""),
    marketing_opt_in: str = Form(""),
    session: Session = Depends(get_session),
):
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)

    target: Decimal | None = None
    if target_price_kes.strip():
        try:
            target = Decimal(target_price_kes.replace(",", "").strip())
        except Exception:  # noqa: BLE001
            target = None

    # HTML checkbox convention: absent when unchecked, "on" or similar when
    # checked. Anything truthy → opt-in.
    opt_in = bool(marketing_opt_in.strip())

    existing = session.exec(
        select(Alert).where(Alert.product_id == product_id, Alert.email == email.lower())
    ).first()
    if existing:
        existing.target_price_kes = target
        existing.active = True
        # Only elevate the opt-in flag if the user just ticked it; never
        # silently downgrade — user might've opted in previously.
        if opt_in:
            existing.marketing_opt_in = True
        session.add(existing)
        session.commit()
        alert_id = existing.id
    else:
        new_alert = Alert(
            product_id=product_id,
            email=email.lower().strip(),
            target_price_kes=target,
            active=True,
            marketing_opt_in=opt_in,
        )
        session.add(new_alert)
        session.commit()
        alert_id = new_alert.id

    # Add this alert to the anonymous watchlist cookie so the user can find
    # their tracked products later without an account. Signed with SECRET_KEY
    # so a user can't fake other people's alert IDs into the list.
    existing_ids = verify_watchlist_cookie(request.cookies.get("watchlist", ""))
    if alert_id is not None and alert_id not in existing_ids:
        existing_ids.append(alert_id)
    new_cookie = make_watchlist_cookie(existing_ids)

    response = templates.TemplateResponse(
        request,
        "partials/_alert_confirm.html",
        {"product": product, "email": email, "target": target},
    )
    response.set_cookie(
        "watchlist",
        new_cookie,
        max_age=_WATCHLIST_COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/watchlist", response_class=HTMLResponse)
def watchlist(request: Request, session: Session = Depends(get_session)):
    """List the alerts this browser has created.

    Cookie-based (no account). If someone clears cookies or switches
    browsers/devices, they lose the view — that's the tradeoff for skipping
    auth. The unsubscribe email each user gets is the durable record.
    """
    ids = verify_watchlist_cookie(request.cookies.get("watchlist", ""))
    items: list[dict] = []
    if ids:
        rows = session.exec(
            select(
                Alert,
                Product,
                func.min(Listing.price_kes).label("min_price"),
                func.count(Listing.id).label("offer_count"),
            )
            .join(Product, Product.id == Alert.product_id)
            .join(Listing, Listing.product_id == Product.id, isouter=True)
            .where(Alert.id.in_(ids))
            .group_by(Alert.id, Product.id)
        ).all()
        for alert, product, min_price, offer_count in rows:
            items.append(
                {
                    "alert": alert,
                    "product": product,
                    "min_price": min_price,
                    "offer_count": offer_count or 0,
                }
            )
        # Sort active first, then by most-recently-created.
        items.sort(key=lambda i: (not i["alert"].active, -(i["alert"].id or 0)))
    return templates.TemplateResponse(
        request,
        "watchlist.html",
        {"items": items},
    )


@router.get("/alerts/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """One-click unsubscribe from a single alert.

    Token is HMAC-signed with `settings.secret_key` (see `alerts.tokens`), so
    invalid tokens 400 without touching the DB. Idempotent — visiting the
    link twice just leaves the alert inactive.
    """
    alert_id = verify_unsubscribe_token(token)
    if alert_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired unsubscribe link")
    alert = session.get(Alert, alert_id)
    product = None
    if alert:
        product = session.get(Product, alert.product_id)
        if alert.active:
            alert.active = False
            session.add(alert)
            session.commit()
    response = templates.TemplateResponse(
        request,
        "unsubscribed.html",
        {"product": product},
    )
    # Prune the id from the browser's watchlist cookie so the unsubscribed
    # alert stops showing up on /watchlist. Only touches this browser — other
    # devices tracking the same alert lose it via the DB flip above.
    existing_ids = verify_watchlist_cookie(request.cookies.get("watchlist", ""))
    if alert_id in existing_ids:
        existing_ids = [i for i in existing_ids if i != alert_id]
        response.set_cookie(
            "watchlist",
            make_watchlist_cookie(existing_ids),
            max_age=_WATCHLIST_COOKIE_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
    return response
