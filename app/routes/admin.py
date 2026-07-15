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

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func as sa_func
from sqlalchemy import update
from sqlmodel import Session, select

from app.config import settings
from app.templating import templates
from db.models import Alert, Listing, Product, ProductMergeCandidate, Review, ReviewReport
from db.session import get_session
from scripts.scrape_health import merchant_health

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(
    x_admin_key: str | None = Header(default=None),
    admin_key_cookie: str | None = Cookie(default=None, alias="admin_key"),
    admin_key_query: str | None = Query(default=None, alias="admin_key"),
) -> None:
    """Verify the caller supplied a valid admin key via one of three routes.

    Cookie mirroring lives in app/main.py's `_admin_cookie_mirror`
    middleware — a Depends-injected Response can't set cookies on the
    TemplateResponse that admin endpoints return, so the middleware
    handles cross-cutting cookie-set duty for every /admin/* response.
    """
    if not settings.admin_key:
        raise HTTPException(status_code=404)
    provided = x_admin_key or admin_key_cookie or admin_key_query
    if not provided or provided != settings.admin_key:
        raise HTTPException(status_code=401, detail="admin key required")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def admin_index(
    request: Request,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """One-page overview: summary counters for every admin subsystem so you
    don't have to click into each detail page to see if there's anything
    to look at. Each tile links to its detail page."""
    scrape_rows = merchant_health(session)
    scrapes_stale = sum(
        1 for r in scrape_rows
        if r.hours_since_last_check is not None and r.hours_since_last_check > 24
    )
    scrapes_never = sum(1 for r in scrape_rows if r.hours_since_last_check is None)

    alerts_active = session.exec(
        select(sa_func.count(Alert.id)).where(Alert.active.is_(True))
    ).one() or 0
    alerts_emails = session.exec(
        select(sa_func.count(sa_func.distinct(Alert.email)))
        .where(Alert.active.is_(True))
    ).one() or 0
    alerts_marketing = session.exec(
        select(sa_func.count(sa_func.distinct(Alert.email)))
        .where(Alert.marketing_opt_in.is_(True))
    ).one() or 0

    reviews_total = session.exec(select(sa_func.count(Review.id))).one() or 0
    reviews_pending = session.exec(
        select(sa_func.count(Review.id)).where(Review.verified_at.is_(None))
    ).one() or 0
    reviews_flagged = session.exec(
        select(sa_func.count(sa_func.distinct(ReviewReport.review_id)))
    ).one() or 0

    merge_pending = session.exec(
        select(sa_func.count(ProductMergeCandidate.id))
        .where(ProductMergeCandidate.status == "pending")
    ).one() or 0
    merge_approved = session.exec(
        select(sa_func.count(ProductMergeCandidate.id))
        .where(ProductMergeCandidate.status == "approved")
    ).one() or 0

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "scrapes": {
                "total": len(scrape_rows),
                "stale": scrapes_stale,
                "never": scrapes_never,
            },
            "alerts": {
                "active": alerts_active,
                "emails": alerts_emails,
                "marketing": alerts_marketing,
            },
            "reviews": {
                "total": reviews_total,
                "pending": reviews_pending,
                "flagged": reviews_flagged,
            },
            "merge": {
                "pending": merge_pending,
                "approved": merge_approved,
            },
            "now_utc": datetime.now(UTC),
        },
    )


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


# ---------------------------------------------------------------------------
# Scrape health — /admin/scrapes
# ---------------------------------------------------------------------------


@router.get("/scrapes", response_class=HTMLResponse)
def scrapes_dashboard(
    request: Request,
    stale_hours: float = Query(default=24.0, ge=1.0, le=720.0),
    delist_message: str | None = Query(default=None),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Per-merchant scrape freshness. Same data as
    `python -m scripts.scrape_health`, viewable behind the admin key."""
    rows = merchant_health(session)
    stale_count = sum(
        1 for r in rows
        if r.hours_since_last_check is not None and r.hours_since_last_check > stale_hours
    )
    never_count = sum(1 for r in rows if r.hours_since_last_check is None)
    return templates.TemplateResponse(
        request,
        "admin/scrapes.html",
        {
            "rows": rows,
            "stale_hours": stale_hours,
            "stale_count": stale_count,
            "never_count": never_count,
            "now_utc": datetime.now(UTC),
            "admin_key": settings.admin_key,
            "delist_message": delist_message,
        },
    )


@router.post("/scrapes/delist-stale")
def delist_stale(
    days: int = Form(...),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Flip `in_stock=false` on every Listing whose last_checked_at is
    older than `days` days ago.

    Non-destructive: we keep the Listing row itself and its PriceHistory
    so product pages can still show the merchant's historical prices —
    just marks the offer as no-longer-available. Next successful scrape
    that re-sees the item will flip it back to in-stock automatically.

    This is the manual button-press equivalent of a "reap dead listings"
    background job. Bounded to days ∈ [1, 90] so a stray zero doesn't
    delist the entire catalog in one click.
    """
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be 1-90")
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = session.exec(
        update(Listing)
        .where(Listing.last_checked_at < cutoff)
        .where(Listing.in_stock.is_(True))
        .values(in_stock=False)
    )
    session.commit()
    n = result.rowcount if result.rowcount is not None else 0
    msg = f"Delisted {n} listing{'' if n == 1 else 's'} untouched for >{days} days."
    return RedirectResponse(
        url=f"/admin/scrapes?delist_message={msg}", status_code=303
    )


# ---------------------------------------------------------------------------
# Price alerts — /admin/alerts
# ---------------------------------------------------------------------------


def _alerts_query(filter_: str, search: str | None):
    """Build the SELECT for the alerts dashboard + CSV export.

    Kept as one helper so the HTML view and the CSV download can't drift —
    both apply the same filter semantics.
    """
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(500)
    if filter_ == "active":
        stmt = (
            select(Alert)
            .where(Alert.active.is_(True))
            .order_by(Alert.created_at.desc())
            .limit(500)
        )
    elif filter_ == "marketing":
        stmt = (
            select(Alert)
            .where(Alert.marketing_opt_in.is_(True))
            .order_by(Alert.created_at.desc())
            .limit(500)
        )
    elif filter_ == "fired":
        stmt = (
            select(Alert)
            .where(Alert.last_notified_at.is_not(None))
            .order_by(Alert.last_notified_at.desc())
            .limit(500)
        )
    if search:
        # Case-insensitive substring match on the email column. Works on
        # both sqlite (LIKE is case-insensitive by default) and postgres
        # (ilike). Guard against SQL wildcard characters in the input so
        # a stray '%' in the search box doesn't accidentally match all rows.
        needle = f"%{search.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(Alert.email.ilike(needle))
    return stmt


@router.get("/alerts", response_class=HTMLResponse)
def admin_alerts(
    request: Request,
    filter: str = Query(default="active"),  # noqa: A002 — matches URL param name
    search: str | None = Query(default=None),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Price-drop alert signups. Default: active alerts, newest first.

    Filters (query string):
      ?filter=active     → active alerts only (default)
      ?filter=all        → include unsubscribed
      ?filter=marketing  → only signups that opted in to marketing emails
      ?filter=fired      → alerts that have already fired at least once
      ?search=foo        → case-insensitive substring match on email
    """
    alerts = session.exec(_alerts_query(filter, search)).all()

    # Hydrate the referenced products in one query for the row template.
    product_ids = {a.product_id for a in alerts}
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

    # Header counters — cheap aggregate queries independent of filter.
    total_active = session.exec(
        select(sa_func.count(Alert.id)).where(Alert.active.is_(True))
    ).one() or 0
    unique_emails = session.exec(
        select(sa_func.count(sa_func.distinct(Alert.email)))
        .where(Alert.active.is_(True))
    ).one() or 0
    marketing_optins = session.exec(
        select(sa_func.count(sa_func.distinct(Alert.email)))
        .where(Alert.marketing_opt_in.is_(True))
    ).one() or 0

    rows = [
        {"alert": a, "product": products_by_id.get(a.product_id)}
        for a in alerts
    ]

    return templates.TemplateResponse(
        request,
        "admin/alerts.html",
        {
            "rows": rows,
            "active_filter": filter,
            "search": search or "",
            "total_active": total_active,
            "unique_emails": unique_emails,
            "marketing_optins": marketing_optins,
            "admin_key": settings.admin_key,
        },
    )


@router.get("/alerts/export.csv")
def admin_alerts_csv(
    filter: str = Query(default="marketing"),  # noqa: A002
    search: str | None = Query(default=None),
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """CSV export of alert signups matching the current filter.

    Default filter is `marketing` — the common export use-case is pulling
    the opt-in list to send a mailing. Pass `?filter=all` etc. to widen.
    """
    import csv
    import io

    alerts = session.exec(_alerts_query(filter, search)).all()
    product_ids = {a.product_id for a in alerts}
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

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "email", "product_slug", "product_title", "target_price_kes",
        "marketing_opt_in", "active", "created_at", "last_notified_at",
    ])
    for a in alerts:
        p = products_by_id.get(a.product_id)
        w.writerow([
            a.email,
            (p.slug if p else ""),
            (p.title if p else ""),
            (str(a.target_price_kes) if a.target_price_kes is not None else ""),
            "1" if a.marketing_opt_in else "0",
            "1" if a.active else "0",
            a.created_at.isoformat() if a.created_at else "",
            a.last_notified_at.isoformat() if a.last_notified_at else "",
        ])
    from fastapi.responses import Response

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="alerts_{filter}.csv"',
        },
    )


@router.post("/alerts/{alert_id}/unsubscribe")
def admin_alerts_unsubscribe(
    alert_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin),
):
    """Set active=False on an alert — same effect as the user clicking the
    unsubscribe magic link in one of the alert emails. Non-destructive
    so we keep the audit trail; a real user resubscribing goes through
    the normal signup flow and a new Alert row gets created."""
    a = session.get(Alert, alert_id)
    if not a:
        raise HTTPException(status_code=404)
    a.active = False
    session.add(a)
    session.commit()
    return RedirectResponse(url="/admin/alerts", status_code=303)
