"""End-to-end review flow: submit → verify → render.

Reviews stay hidden until the reviewer clicks a magic-link sent to their
email. These tests exercise the whole loop against a real product from
the local DB — same TestClient pattern the alerts tests use.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from alerts.tokens import make_review_verify_token
from app.main import app
from db.models import Product, Review
from db.session import engine


@pytest.fixture()
def product_id() -> int:
    """First product in the DB. The scrape fixtures aren't wired in tests
    yet, so we lean on whatever local sqlite has — CI seeds enough via
    seed.load if the DB is empty."""
    with Session(engine) as s:
        p = s.exec(select(Product).limit(1)).first()
        assert p is not None, "no products in DB; run `python -m seed.load`"
        return p.id


@pytest.fixture(autouse=True)
def _cleanup_reviews():
    """Delete any test-authored reviews after each test so runs don't
    accumulate rows and one test's row doesn't leak into another."""
    yield
    with Session(engine) as s:
        for r in s.exec(
            select(Review).where(Review.email.like("%@test.review.local"))
        ).all():
            s.delete(r)
        s.commit()


def test_pending_review_hidden_from_product_page(product_id: int) -> None:
    c = TestClient(app)
    r = c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": "alice@test.review.local",
            "display_name": "Alice",
            "rating": 4,
            "body": "Decent phone, battery lasts most of the day.",
        },
    )
    assert r.status_code == 200
    assert "check your inbox" in r.text.lower()

    product = _get_product(product_id)
    page = c.get(f"/p/{product.slug}")
    assert "Alice" not in page.text, "unverified review must be hidden"


def test_verify_link_publishes_review(product_id: int) -> None:
    c = TestClient(app)
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": "bob@test.review.local",
            "display_name": "Bob",
            "rating": 5,
            "body": "Best purchase I've made this year, would recommend it.",
        },
    )
    review_id = _get_pending_id("bob@test.review.local")

    r = c.get(f"/reviews/verify/{make_review_verify_token(review_id)}", follow_redirects=False)
    assert r.status_code == 302
    assert "/p/" in r.headers.get("location", "")

    with Session(engine) as s:
        rv = s.get(Review, review_id)
        assert rv.verified_at is not None


def test_verified_review_emits_aggregaterating_jsonld(product_id: int) -> None:
    c = TestClient(app)
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": "carol@test.review.local",
            "display_name": "Carol",
            "rating": 5,
            "body": "Fantastic value for money, everything works as expected.",
        },
    )
    review_id = _get_pending_id("carol@test.review.local")
    c.get(f"/reviews/verify/{make_review_verify_token(review_id)}", follow_redirects=False)

    product = _get_product(product_id)
    page = c.get(f"/p/{product.slug}")
    assert "Carol" in page.text

    m = re.search(r'"aggregateRating":\s*(\{[^}]+\})', page.text)
    assert m is not None, "aggregateRating missing from JSON-LD"
    ar = json.loads(m.group(1))
    assert ar["ratingValue"] == 5.0
    assert ar["reviewCount"] >= 1


def test_bad_verify_token_returns_404() -> None:
    r = TestClient(app).get("/reviews/verify/999.notasignature", follow_redirects=False)
    assert r.status_code == 404


def test_short_body_rejected(product_id: int) -> None:
    r = TestClient(app).post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": "dan@test.review.local",
            "display_name": "Dan",
            "rating": 3,
            "body": "too short",
        },
    )
    assert r.status_code == 400


def test_resubmit_flips_back_to_pending(product_id: int) -> None:
    """Editing a review pulls it back into the pending state so the
    reviewer has to re-verify. Prevents someone who guessed an email +
    product from silently republishing edits."""
    c = TestClient(app)
    email = "eve@test.review.local"
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": email,
            "display_name": "Eve",
            "rating": 5,
            "body": "This is the original review body with enough characters.",
        },
    )
    rid = _get_pending_id(email)
    c.get(f"/reviews/verify/{make_review_verify_token(rid)}", follow_redirects=False)

    with Session(engine) as s:
        rv = s.get(Review, rid)
        assert rv.verified_at is not None
        first_verified_at = rv.verified_at

    # Resubmit with new body
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": email,
            "display_name": "Eve",
            "rating": 4,
            "body": "This is the updated review body with more thoughtful feedback.",
        },
    )
    with Session(engine) as s:
        rv = s.get(Review, rid)
        assert rv.verified_at is None, "resubmit must invalidate old verification"
        assert rv.rating == 4
        assert first_verified_at is not None  # kept in the assertion so linters don't complain


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _get_product(product_id: int) -> Product:
    with Session(engine) as s:
        return s.get(Product, product_id)


def _get_pending_id(email: str) -> int:
    with Session(engine) as s:
        rv = s.exec(select(Review).where(Review.email == email)).first()
        assert rv is not None, f"no review found for {email}"
        return rv.id


# ---------------------------------------------------------------------------
# Moderation + reports
# ---------------------------------------------------------------------------


def _publish_review(email: str, product_id: int, rating: int = 5) -> int:
    """Submit + verify in one call — helper for moderation tests."""
    c = TestClient(app)
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": email,
            "display_name": "Test",
            "rating": rating,
            "body": "Long enough body so the min-char gate lets us through.",
        },
    )
    rid = _get_pending_id(email)
    c.get(f"/reviews/verify/{make_review_verify_token(rid)}", follow_redirects=False)
    return rid


def test_hidden_review_not_rendered_and_excluded_from_aggregate(product_id: int) -> None:
    c = TestClient(app)
    good = _publish_review("frank@test.review.local", product_id, rating=5)
    bad = _publish_review("greta@test.review.local", product_id, rating=1)

    with Session(engine) as s:
        r = s.get(Review, bad)
        from datetime import datetime as _dt
        r.hidden_at = _dt.utcnow()
        r.hidden_reason = "spam"
        s.add(r)
        s.commit()

    product = _get_product(product_id)
    page = c.get(f"/p/{product.slug}").text
    with Session(engine) as s:
        good_row = s.get(Review, good)
    # Good review still visible…
    assert good_row.display_name in page
    # …and the aggregate is now 5.0 / 1 review (bad excluded).
    m = re.search(r'"aggregateRating":\s*(\{[^}]+\})', page)
    assert m
    ar = json.loads(m.group(1))
    assert ar["ratingValue"] == 5.0
    assert ar["reviewCount"] == 1


def test_report_flags_review_once_per_ip(product_id: int) -> None:
    from db.models import ReviewReport

    c = TestClient(app)
    rid = _publish_review("holly@test.review.local", product_id)

    r1 = c.post(f"/reviews/{rid}/report", data={"reason": "spam"})
    assert r1.status_code == 200
    r2 = c.post(f"/reviews/{rid}/report", data={"reason": "duplicate"})
    assert r2.status_code == 200

    # Second POST from the same IP is deduped — still exactly one row.
    with Session(engine) as s:
        rows = s.exec(select(ReviewReport).where(ReviewReport.review_id == rid)).all()
        assert len(rows) == 1
        # And the row is on file for the admin dashboard.
        assert rows[0].reason == "spam"
    # Cleanup so subsequent tests don't inherit the report row.
    with Session(engine) as s:
        for row in s.exec(select(ReviewReport).where(ReviewReport.review_id == rid)).all():
            s.delete(row)
        s.commit()


def test_reviews_policy_page_renders() -> None:
    r = TestClient(app).get("/reviews-policy")
    assert r.status_code == 200
    text = r.text.lower()
    # Sanity: the page mentions the key rules the form links to.
    assert "review guidelines" in text
    assert "publish" in text
    assert "moderate" in text


def test_admin_reviews_requires_key() -> None:
    r = TestClient(app).get("/admin/reviews")
    # 404 when admin_key is unset (dev), 401 when set but not provided.
    assert r.status_code in (404, 401)


def test_edited_at_bumped_on_resubmit(product_id: int) -> None:
    c = TestClient(app)
    email = "ivy@test.review.local"
    _publish_review(email, product_id, rating=5)
    rid = _get_pending_id(email)
    # Second submit
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": email,
            "display_name": "Ivy",
            "rating": 3,
            "body": "Updated body after some real usage of the product for a week.",
        },
    )
    with Session(engine) as s:
        r = s.get(Review, rid)
        assert r.verified_at is None  # resubmit invalidates old verification
        assert r.edited_at is not None
        assert r.rating == 3


def test_marketing_opt_in_stored_when_checked(product_id: int) -> None:
    c = TestClient(app)
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": "jane@test.review.local",
            "display_name": "Jane",
            "rating": 4,
            "body": "Solid enough phone, no complaints from me about the daily use.",
            "marketing_opt_in": "1",
        },
    )
    with Session(engine) as s:
        r = s.exec(select(Review).where(Review.email == "jane@test.review.local")).first()
        assert r.marketing_opt_in is True


def test_marketing_opt_in_off_by_default(product_id: int) -> None:
    c = TestClient(app)
    c.post(
        "/reviews",
        data={
            "product_id": product_id,
            "email": "kyle@test.review.local",
            "display_name": "Kyle",
            "rating": 5,
            "body": "Battery is decent, screen is bright, works as advertised.",
            # marketing_opt_in omitted entirely
        },
    )
    with Session(engine) as s:
        r = s.exec(select(Review).where(Review.email == "kyle@test.review.local")).first()
        assert r.marketing_opt_in is False
