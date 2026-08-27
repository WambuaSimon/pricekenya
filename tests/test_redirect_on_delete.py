"""Every path that deletes a Product must leave a ProductRedirect behind.

A deleted product slug is a URL Google has probably indexed. Deleting the
row without recording where it went turns that URL into a permanent 404
and discards whatever link equity it accrued.

The rule was documented on the ProductRedirect model but only honoured by
scripts/coarsen_phones_backfill.py. `/admin/merge-review` approve and
scripts/normalize_products.py both deleted silently, so the production
table sat at 0 rows while Search Console reported 93 "Not found (404)" —
and the 301 fallback in app/routes/products.py was querying an empty
table on every miss.

These tests pin the rule to each caller, so a fourth deletion path can't
be added without one of them going red.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlmodel import select

from db.models import Listing, Merchant, Product, ProductRedirect
from db.redirects import record_redirect


def _product(session, slug: str, key: str) -> Product:
    p = Product(
        slug=slug, canonical_key=key, brand="brand", model=slug,
        title=slug.replace("-", " ").title(), category_slug="phones",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _listing(session, product_id: int, merchant_id: int, title: str = "L") -> Listing:
    lst = Listing(
        product_id=product_id, merchant_id=merchant_id,
        url=f"https://m{merchant_id}.example/{product_id}",
        title_on_merchant=title, price_kes=Decimal("1000"), in_stock=True,
        last_checked_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(lst)
    session.commit()
    return lst


# --------------------------------------------------------------- helper


def test_chain_collapses_to_one_hop(session):
    """A → B, then B merged into C, must rewrite A → C.

    Without this, the visitor holding A is redirected to B, which no
    longer exists, and 404s anyway — a redirect that doesn't redirect.
    """
    record_redirect(session, old_slug="a", new_slug="b")
    record_redirect(session, old_slug="b", new_slug="c")
    session.commit()

    rows = {r.old_slug: r.new_slug for r in session.exec(select(ProductRedirect)).all()}
    assert rows == {"a": "c", "b": "c"}


def test_no_self_redirect(session):
    """A slug must never point at itself — product_detail would bounce a
    404 into a redirect loop."""
    record_redirect(session, old_slug="a", new_slug="a")
    session.commit()
    assert session.exec(select(ProductRedirect)).all() == []


def test_chain_rewrite_does_not_create_self_redirect(session):
    """B → A followed by A → B would rewrite B's target to B itself."""
    record_redirect(session, old_slug="b", new_slug="a")
    record_redirect(session, old_slug="a", new_slug="b")
    session.commit()

    rows = {r.old_slug: r.new_slug for r in session.exec(select(ProductRedirect)).all()}
    assert "b" not in rows or rows["b"] != "b"


def test_repeated_call_is_idempotent(session):
    record_redirect(session, old_slug="a", new_slug="b")
    record_redirect(session, old_slug="a", new_slug="b")
    session.commit()
    assert len(session.exec(select(ProductRedirect)).all()) == 1


# ------------------------------------------------- caller: admin approve


@pytest.fixture
def admin_client(session, monkeypatch):
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app
    from db.session import get_session

    monkeypatch.setattr(config.settings, "admin_key", "top-secret")

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_admin_merge_approve_records_redirect(session, admin_client):
    """The /admin/merge-review approve handler is the path a human uses
    most, and was the one silently dropping slugs."""
    from db.models import ProductMergeCandidate

    session.add(Merchant(id=1, slug="m1", name="M1", base_url="https://m1.example"))
    source = _product(session, "samsung-s25-128", "samsung|s25|128")
    target = _product(session, "samsung-s25", "samsung|s25")
    _listing(session, source.id, 1)
    cand = ProductMergeCandidate(
        source_product_id=source.id,
        target_product_id=target.id,
        similarity=0.95,
        source_title="Samsung S25 128GB",
        status="pending",
    )
    session.add(cand)
    session.commit()
    session.refresh(cand)

    resp = admin_client.post(
        f"/admin/merge-review/{cand.id}/approve",
        headers={"X-Admin-Key": "top-secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text[:300]

    assert session.get(Product, source.id) is None, "source should be deleted"
    redirect = session.get(ProductRedirect, "samsung-s25-128")
    assert redirect is not None, "approve deleted a product without a redirect"
    assert redirect.new_slug == "samsung-s25"


# -------------------------------------------- caller: normalize_products


def test_normalize_products_records_redirect(session):
    """When normalize moves a product's only listing elsewhere and then
    deletes the emptied product, the vacated slug must 301 to wherever
    the listing landed."""
    from scripts.normalize_products import Plan, _apply

    session.add(Merchant(id=1, slug="m1", name="M1", base_url="https://m1.example"))
    old = _product(session, "old-slug", "brand|old")
    new = _product(session, "new-slug", "brand|new")
    lst = _listing(session, old.id, 1)

    plan = Plan(
        moves=[(lst.id, new.id, "brand|old", "brand|new")],
        creates={},
        deletes_listings=[],
        deletes_products=[(old.id, "brand|old")],
    )
    _apply(session, plan, {})

    assert session.get(Product, old.id) is None
    redirect = session.get(ProductRedirect, "old-slug")
    assert redirect is not None, "normalize deleted a product without a redirect"
    assert redirect.new_slug == "new-slug"


def test_normalize_no_redirect_when_there_is_no_successor(session):
    """A product emptied by DELETED listings (not moves) has nowhere to
    point. A 404 is the honest answer — don't invent a target."""
    from scripts.normalize_products import Plan, _apply

    session.add(Merchant(id=1, slug="m1", name="M1", base_url="https://m1.example"))
    old = _product(session, "junk-slug", "brand|junk")
    lst = _listing(session, old.id, 1)

    plan = Plan(
        moves=[],
        creates={},
        deletes_listings=[(lst.id, "camera mount")],
        deletes_products=[(old.id, "brand|junk")],
    )
    _apply(session, plan, {})

    assert session.get(Product, old.id) is None
    assert session.get(ProductRedirect, "junk-slug") is None


def test_normalize_picks_plurality_target_when_listings_scatter(session):
    """Listings from one product can scatter across several targets.
    Redirect to the one that took the most — the closest thing to a
    successor, and better than a 404 for everyone."""
    from scripts.normalize_products import Plan, _apply

    for mid in (1, 2, 3):
        session.add(Merchant(id=mid, slug=f"m{mid}", name=f"M{mid}",
                             base_url=f"https://m{mid}.example"))
    old = _product(session, "scattered", "brand|scattered")
    big = _product(session, "big-target", "brand|big")
    small = _product(session, "small-target", "brand|small")
    l1 = _listing(session, old.id, 1)
    l2 = _listing(session, old.id, 2)
    l3 = _listing(session, old.id, 3)

    plan = Plan(
        moves=[
            (l1.id, big.id, "brand|scattered", "brand|big"),
            (l2.id, big.id, "brand|scattered", "brand|big"),
            (l3.id, small.id, "brand|scattered", "brand|small"),
        ],
        creates={},
        deletes_listings=[],
        deletes_products=[(old.id, "brand|scattered")],
    )
    _apply(session, plan, {})

    redirect = session.get(ProductRedirect, "scattered")
    assert redirect is not None
    assert redirect.new_slug == "big-target", "should follow the plurality of listings"


def test_rematch_washer_dryers_records_redirect(session):
    """The washer-dryer re-home is the newest deletion path.

    When the combo-capacity fix moves every listing off a product that was
    built entirely from mis-parsed titles — 26 of them on prod — the vacated
    slug has to 301 to wherever those listings went.
    """
    from scripts.rematch_washer_dryers import run

    session.add(Merchant(id=1, slug="m1", name="M1", base_url="https://m1.example"))
    session.commit()

    # `lg|8kg|front` is the collision itself: the combo below used to key
    # here, on top of the genuine 8kg washer.
    old = _product(session, "lg-8kg-front-washer-dryer", "lg|8kg|front|with-dryer")
    old.category_slug = "washers-dryers"
    session.add(old)
    session.commit()
    _listing(
        session, old.id, 1,
        title="LG 15/8 Kg Front Load Washer and Dryer F0Z6DRP24",
    )
    # Capture primitives up front: the script commits its deletes from its
    # own Session, after which touching `old.<attr>` here would trigger a
    # refresh of a row that no longer exists.
    old_id, old_slug = old.id, old.slug

    run(category="washers-dryers", apply=True)
    session.expire_all()

    assert session.get(Product, old_id) is None, "emptied product should be deleted"
    redirect = session.get(ProductRedirect, old_slug)
    assert redirect is not None, "re-home deleted a product without a redirect"

    # It points at the product the listing actually moved to: 15kg, not 8kg.
    landed = session.exec(
        select(Product).where(Product.canonical_key == "lg|15kg|front|with-dryer")
    ).first()
    assert landed is not None
    assert redirect.new_slug == landed.slug


def test_rematch_leaves_correctly_keyed_listings_alone(session):
    """The re-home must not churn rows that are already right."""
    from scripts.rematch_washer_dryers import run

    session.add(Merchant(id=1, slug="m1", name="M1", base_url="https://m1.example"))
    session.commit()
    keep = _product(session, "lg-8kg-front", "lg|8kg|front")
    keep.category_slug = "washers-dryers"
    session.add(keep)
    session.commit()
    lst = _listing(
        session, keep.id, 1,
        title="LG F4J3TYG6J Front Load Washing Machine, 8KG",
    )
    keep_id, lst_id = keep.id, lst.id

    moved = run(category="washers-dryers", apply=True)
    session.expire_all()

    assert moved == 0
    assert session.get(Product, keep_id) is not None
    assert session.get(Listing, lst_id).product_id == keep_id
