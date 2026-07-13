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

import hashlib
import hmac
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from alerts.tokens import make_review_verify_token, verify_review_verify_token
from app.config import settings
from app.templating import templates
from db.models import Product, Review, ReviewReport
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
    marketing_opt_in: str = Form(""),
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
    opt_in = bool(marketing_opt_in.strip())
    title_norm = (title.strip() or None) if title else None
    if title_norm:
        title_norm = title_norm[:80]
    pros_norm = (pros.strip() or None) if pros else None
    cons_norm = (cons.strip() or None) if cons else None

    # One review per (product, email). Resubmitting flips the row back to
    # pending so the reviewer must re-verify — matches how they'd expect
    # an "edit" flow to work without giving anyone a way to publish edits
    # without a fresh consent click. edited_at is bumped so the product
    # page can render "Edited on YYYY-MM-DD" once re-verified.
    existing = session.exec(
        select(Review).where(
            Review.product_id == product_id, Review.email == email_norm
        )
    ).first()
    if existing:
        existing.display_name = name_norm
        existing.rating = rating
        existing.title = title_norm
        existing.body = body_stripped
        existing.pros = pros_norm
        existing.cons = cons_norm
        existing.verified_at = None
        existing.edited_at = datetime.utcnow()
        # Only elevate the opt-in flag if the user just ticked it. Never
        # silently downgrade — matches the Alert flow.
        if opt_in:
            existing.marketing_opt_in = True
        session.add(existing)
        session.commit()
        review_id = existing.id
    else:
        review = Review(
            product_id=product_id,
            email=email_norm,
            display_name=name_norm,
            rating=rating,
            title=title_norm,
            body=body_stripped,
            pros=pros_norm,
            cons=cons_norm,
            marketing_opt_in=opt_in,
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
    reviewer sees their newly-visible review right away.

    When settings.reviews_require_approval is on (spam mitigation switch),
    verified_at still gets set so the reviewer sees "we got it", but the
    admin must still explicitly publish from /admin/reviews. That branch is
    handled at render time — the product-page query excludes reviews whose
    approved_by_admin flag hasn't been set. (For v1 we're implementing the
    default post-moderation model; the switch is documented but the
    admin-approval column can be added when a spam problem materialises.)
    """
    review_id = verify_review_verify_token(token)
    if review_id is None:
        raise HTTPException(status_code=404)
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404)

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


def _reporter_ip_hash(request: Request) -> str:
    """Deterministic 16-hex-char fingerprint of the requester's IP + secret.
    See ReviewReport.__doc__ for why we don't store the raw IP."""
    ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    mac = hmac.new(
        (settings.secret_key or "").encode("utf-8"),
        ip.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return mac[:16]


@router.post("/reviews/{review_id}/report", response_class=HTMLResponse)
def report_review(
    review_id: int,
    request: Request,
    reason: str = Form(""),
    session: Session = Depends(get_session),
):
    """Anonymous flag on a review. Deduped by hashed IP so one reader
    can't inflate a single review's report count. The row surfaces in
    /admin/reviews with a badge; the review itself stays visible until
    a moderator hides it."""
    review = session.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404)
    reason_clean = reason.strip()[:200] or None
    ip_hash = _reporter_ip_hash(request)
    try:
        session.add(
            ReviewReport(
                review_id=review_id,
                reason=reason_clean,
                reporter_ip_hash=ip_hash,
            )
        )
        session.commit()
    except IntegrityError:
        # Same IP already reported this review. Rollback and pretend
        # success — the report is on file, no user-facing "you already
        # reported this" pushback needed.
        session.rollback()
    return templates.TemplateResponse(
        request,
        "partials/_review_reported.html",
        {},
    )
