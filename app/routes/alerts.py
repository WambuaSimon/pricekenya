from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

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

    existing = session.exec(
        select(Alert).where(Alert.product_id == product_id, Alert.email == email.lower())
    ).first()
    if existing:
        existing.target_price_kes = target
        existing.active = True
        session.add(existing)
    else:
        session.add(
            Alert(
                product_id=product_id,
                email=email.lower().strip(),
                target_price_kes=target,
                active=True,
            )
        )
    session.commit()

    return templates.TemplateResponse(
        request,
        "partials/_alert_confirm.html",
        {"product": product, "email": email, "target": target},
    )
