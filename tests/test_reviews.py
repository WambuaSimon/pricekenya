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
