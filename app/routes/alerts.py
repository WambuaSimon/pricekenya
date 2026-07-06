from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from alerts.tokens import verify_unsubscribe_token
from app.templating import templates
from db.models import Alert, Product
from db.session import get_session

router = APIRouter()


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
    else:
        session.add(
            Alert(
                product_id=product_id,
                email=email.lower().strip(),
                target_price_kes=target,
                active=True,
                marketing_opt_in=opt_in,
            )
        )
    session.commit()

    return templates.TemplateResponse(
        request,
        "partials/_alert_confirm.html",
        {"product": product, "email": email, "target": target},
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
    return templates.TemplateResponse(
        request,
        "unsubscribed.html",
        {"product": product},
    )
