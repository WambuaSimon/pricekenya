"""Admin routes — gated by a shared-secret X-Admin-Key header.

`/admin/merge-review` surfaces Phase 1 near-duplicate product pairs (cosine
in [0.90, 0.95)) for manual approve/reject. Auto-merges (≥0.95) don't land
here — they've already been resolved during ingest.

Auth: the shared secret lives in `settings.admin_key`. When empty, every
request is rejected (defence-in-depth: no admin_key in prod = no admin
routes). Sent as `X-Admin-Key: <value>`; also accepted as a cookie
`admin_key=<value>` so a browser can browse the page after one curl call.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func as sa_func
from sqlalchemy import update
from sqlmodel import Session, select

from app.config import settings
from app.templating import templates
from db.models import Listing, Product, ProductMergeCandidate, Review, ReviewReport
from db.session import get_session

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(
    x_admin_key: str | None = Header(default=None),
    admin_key_cookie: str | None = Cookie(default=None, alias="admin_key"),
    admin_key_query: str | None = Query(default=None, alias="admin_key"),
) -> None:
    if not settings.admin_key:
        raise HTTPException(status_code=404)
    provided = x_admin_key or admin_key_cookie or admin_key_query
    if not provided or provided != settings.admin_key:
        raise HTTPException(status_code=401, detail="admin key required")


@router.get("/merge-review", response_class=HTMLResponse)
def merge_review(
    request: Request,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    candidates = session.exec(
        select(ProductMergeCandidate)
        .where(ProductMergeCandidate.status == "pending")
        .order_by(ProductMergeCandidate.similarity.desc())
        .limit(200)
    ).all()

    # Hydrate the two Product rows per candidate for the template.
    rows: list[dict] = []
    for c in candidates:
        source = session.get(Product, c.source_product_id)
        target = session.get(Product, c.target_product_id)
        if not (source and target):
            continue
        rows.append({"candidate": c, "source": source, "target": target})

    response = templates.TemplateResponse(
        request,
        "admin/merge_review.html",
        {"rows": rows, "admin_key": settings.admin_key},
    )
    # If the request came in via header or query string, mirror it into a
    # cookie so subsequent clicks in the browser don't need the header or
    # keep the key in the URL bar.
    header_used = bool(request.headers.get("x-admin-key"))
    query_used = bool(request.query_params.get("admin_key"))
    cookie_missing = not request.cookies.get("admin_key")
    if (header_used or query_used) and cookie_missing:
        # If they came in via query string, redirect to strip the key from
        # the URL bar (so it doesn't stay in browser history / referer).
        if query_used:
            response = RedirectResponse(url="/admin/merge-review", status_code=303)
        response.set_cookie(
            "admin_key",
            settings.admin_key,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 8,  # 8h — short so a leaked machine doesn't leak long
        )
    return response


def _reparent_listings(session: Session, source_id: int, target_id: int) -> None:
    # Bulk UPDATE so SQLAlchemy's identity map doesn't try to null out the
    # relationship when we later delete the source Product. Expire any
    # cached Listing instances so subsequent reads see the new FK.
    session.execute(
        update(Listing)
        .where(Listing.product_id == source_id)
        .values(product_id=target_id)
    )
    session.expire_all()


@router.post("/merge-review/{cand_id}/approve")
def approve(
    cand_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    cand = session.get(ProductMergeCandidate, cand_id)
    if not cand or cand.status != "pending":
        raise HTTPException(status_code=404)
    source = session.get(Product, cand.source_product_id)
    target = session.get(Product, cand.target_product_id)
    if not (source and target):
        cand.status = "rejected"
        cand.reviewed_at = datetime.utcnow()
        cand.reviewer_note = "one side deleted before review"
        session.add(cand)
        session.commit()
        return RedirectResponse(url="/admin/merge-review", status_code=303)

    # Copy over enrichment target lacks so the merge doesn't lose info.
    if not target.image_url and source.image_url:
        target.image_url = source.image_url
    if not target.description and source.description:
        target.description = source.description
    session.add(target)

    _reparent_listings(session, source.id, target.id)

    cand.status = "approved"
    cand.reviewed_at = datetime.utcnow()
    session.add(cand)

    session.delete(source)
    session.commit()
    return RedirectResponse(url="/admin/merge-review", status_code=303)


@router.post("/merge-review/{cand_id}/reject")
def reject(
    cand_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    cand = session.get(ProductMergeCandidate, cand_id)
    if not cand or cand.status != "pending":
        raise HTTPException(status_code=404)
    cand.status = "rejected"
    cand.reviewed_at = datetime.utcnow()
    session.add(cand)
    session.commit()
    return RedirectResponse(url="/admin/merge-review", status_code=303)


# ---------------------------------------------------------------------------
# Review moderation — post-moderation model
# ---------------------------------------------------------------------------


@router.get("/reviews", response_class=HTMLResponse)
def admin_reviews(
    request: Request,
    filter: str = Query(default="all"),  # noqa: A002 — matches URL param name
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Post-moderation queue. Default view: everything, newest first.
    Filter shortcuts:
      ?filter=flagged     → only reviews with at least one report
      ?filter=unverified  → email-verify still pending
      ?filter=hidden      → reviews an admin already hid (audit view)
      ?filter=recent      → last 24 hours
    """
    stmt = select(Review).order_by(Review.created_at.desc()).limit(300)
    if filter == "unverified":
        stmt = (
            select(Review)
            .where(Review.verified_at.is_(None))
            .order_by(Review.created_at.desc())
            .limit(300)
        )
    elif filter == "hidden":
        stmt = (
            select(Review)
            .where(Review.hidden_at.is_not(None))
            .order_by(Review.hidden_at.desc())
            .limit(300)
        )
    elif filter == "recent":
        cutoff = datetime.utcnow() - timedelta(hours=24)
        stmt = (
            select(Review)
            .where(Review.created_at >= cutoff)
            .order_by(Review.created_at.desc())
            .limit(300)
        )
    reviews = session.exec(stmt).all()

    product_ids = {r.product_id for r in reviews}
    products_by_id = (
        {
            p.id: p
            for p in session.exec(
                select(Product).where(Product.id.in_(product_ids))
            ).all()
        }
        if product_ids
        else {}
    )

    report_rows = (
        session.exec(
            select(ReviewReport.review_id, sa_func.count(ReviewReport.id))
            .group_by(ReviewReport.review_id)
        ).all()
        if reviews
        else []
    )
    reports_by_id = {rid: n for rid, n in report_rows}

    if filter == "flagged":
        reviews = [r for r in reviews if reports_by_id.get(r.id, 0) > 0]

    rows = [
        {
            "review": r,
            "product": products_by_id.get(r.product_id),
            "report_count": reports_by_id.get(r.id, 0),
        }
        for r in reviews
    ]

    return templates.TemplateResponse(
        request,
        "admin/reviews.html",
        {"rows": rows, "active_filter": filter},
    )


@router.post("/reviews/{review_id}/hide")
def hide_review(
    review_id: int,
    reason: str = Form(""),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Soft-hide. hidden_at is checked in the product route so the row
    disappears publicly immediately. Row stays for audit — use /delete
    for hard removal."""
    r = session.get(Review, review_id)
    if not r:
        raise HTTPException(status_code=404)
    r.hidden_at = datetime.utcnow()
    r.hidden_reason = reason.strip()[:200] or None
    session.add(r)
    session.commit()
    return RedirectResponse(url="/admin/reviews", status_code=303)


@router.post("/reviews/{review_id}/unhide")
def unhide_review(
    review_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    r = session.get(Review, review_id)
    if not r:
        raise HTTPException(status_code=404)
    r.hidden_at = None
    r.hidden_reason = None
    session.add(r)
    session.commit()
    return RedirectResponse(url="/admin/reviews", status_code=303)


@router.post("/reviews/{review_id}/delete")
def delete_review(
    review_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Hard delete. Only for outright spam / abuse — otherwise prefer /hide
    so we can audit the historical action later. Cascades to reports."""
    r = session.get(Review, review_id)
    if not r:
        raise HTTPException(status_code=404)
    for rep in session.exec(
        select(ReviewReport).where(ReviewReport.review_id == review_id)
    ).all():
        session.delete(rep)
    session.delete(r)
    session.commit()
    return RedirectResponse(url="/admin/reviews", status_code=303)
