"""User-review endpoints: submit + verify.

Reviews are hidden until the author clicks a magic link sent to their
email. That's the only anti-spam gate. `Review.verified_at IS NULL` →
never rendered; anything else → visible on the product page. See
db/models.Review.__doc__ for the rest of the shape.

Email delivery reuses the Resend integration from alerts/dispatcher —
if RESEND_API_KEY is unset the magic link is printed to stdout so local
dev flows still work.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from alerts.tokens import make_review_verify_token, verify_review_verify_token
from app.config import settings
from app.templating import templates
from db.models import Product, Review
from db.session import get_session

router = APIRouter()
log = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_MIN_BODY_CHARS = 30
_MAX_BODY_CHARS = 3000


def _send_verify_email(to: str, product: Product, verify_url: str) -> bool:
    """Send the magic-link verification. Best-effort; logs and returns
    False if we can't send. The review still exists as pending — the
    reviewer can hit "resend" (v2) or just resubmit."""
    subject = f"Confirm your review for {product.title[:60]} — PriceKenya"
    text = (
        f"Thanks for reviewing {product.title} on PriceKenya!\n\n"
        f"Click this link to publish your review:\n{verify_url}\n\n"
        "If you didn't submit a review, ignore this email."
    )
    html = (
        f"<p>Thanks for reviewing <strong>{product.title}</strong> on PriceKenya.</p>"
        f'<p><a href="{verify_url}" style="background:#059669;color:#fff;padding:10px 16px;'
        'border-radius:6px;text-decoration:none;display:inline-block;">Publish my review</a></p>'
        "<p style=\"color:#64748b;font-size:12px;\">If you didn't submit a review, ignore this email.</p>"
    )
    if not settings.resend_api_key:
        log.warning("RESEND_API_KEY unset — logging review verify link instead of sending")
        print(f"[reviews] verify link (would email {to}): {verify_url}")
        return False
    try:
        resp = httpx.post(
            _RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.alerts_from_email,
                "to": [to],
                "subject": subject,
                "text": text,
                "html": html,
            },
            timeout=15.0,
        )
        if resp.status_code >= 400:
            log.error("Resend review-verify %s: %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception:  # noqa: BLE001
        log.exception("Resend review-verify send failed")
        return False


@router.post("/reviews", response_class=HTMLResponse)
def create_review(
    request: Request,
    product_id: int = Form(...),
    email: str = Form(...),
    display_name: str = Form(...),
    rating: int = Form(...),
    body: str = Form(...),
    title: str = Form(""),
    pros: str = Form(""),
    cons: str = Form(""),
    session: Session = Depends(get_session),
):
    """Create or replace a pending review. Sends the reviewer a magic-link
    email; the row is invisible until they click. Returns an HTMX-friendly
    confirmation fragment."""
    product = session.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404)
    if not (1 <= rating <= 5):
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    body_stripped = body.strip()
    if len(body_stripped) < _MIN_BODY_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"body must be at least {_MIN_BODY_CHARS} characters",
        )
    if len(body_stripped) > _MAX_BODY_CHARS:
        body_stripped = body_stripped[:_MAX_BODY_CHARS]

    email_norm = email.lower().strip()
    name_norm = display_name.strip()[:40] or "Anonymous"

    # One review per (product, email). Resubmitting flips the row back to
    # pending so the reviewer must re-verify — matches how they'd expect
    # an "edit" flow to work without giving anyone a way to publish edits
    # without a fresh consent click.
    existing = session.exec(
        select(Review).where(
            Review.product_id == product_id, Review.email == email_norm
        )
    ).first()
    if existing:
        existing.display_name = name_norm
        existing.rating = rating
        existing.title = (title.strip() or None)[:80] if title else None
        existing.body = body_stripped
        existing.pros = (pros.strip() or None) if pros else None
        existing.cons = (cons.strip() or None) if cons else None
        existing.verified_at = None
        session.add(existing)
        session.commit()
        review_id = existing.id
    else:
        review = Review(
            product_id=product_id,
            email=email_norm,
            display_name=name_norm,
            rating=rating,
            title=(title.strip() or None)[:80] if title else None,
            body=body_stripped,
            pros=(pros.strip() or None) if pros else None,
            cons=(cons.strip() or None) if cons else None,
        )
        session.add(review)
        session.commit()
        session.refresh(review)
        review_id = review.id

    base = str(request.base_url).rstrip("/")
    verify_url = f"{base}/reviews/verify/{make_review_verify_token(review_id)}"
    _send_verify_email(email_norm, product, verify_url)

    return templates.TemplateResponse(
        request,
        "partials/_review_pending.html",
        {"email": email_norm},
    )


@router.get("/reviews/verify/{token}")
def verify_review(token: str, session: Session = Depends(get_session)):
    """Flip verified_at → now(). Redirect to the product page so the
    reviewer sees their newly-visible review right away."""
    review_id = verify_review_verify_token(token)
    if review_id is None:
        raise HTTPException(status_code=404)
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404)
    from datetime import datetime

    if review.verified_at is None:
        review.verified_at = datetime.utcnow()
        session.add(review)
        session.commit()
    product = session.get(Product, review.product_id)
    if not product:
        # Shouldn't happen — product would have to be deleted between
        # posting the review and clicking the link.
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/p/{product.slug}#reviews", status_code=302)
