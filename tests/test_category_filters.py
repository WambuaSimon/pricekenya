"""Regression tests for the /c/<slug> filter facets.

Every test seeds a tiny catalogue against the in-memory sqlite session
fixture and overrides get_session so TestClient's request handlers reach
the same DB. Nothing here touches prod Neon.

Covers:
  - No filters returns every product in the category.
  - Brand facet narrows the returned set.
  - JSON-nested spec facets work (astext bridge for the SQLite/Postgres split).
  - Range facet (price_max) filters on the aggregate min_price.
  - Bool facet (in_stock=1) drops products with no in-stock listings.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from db.models import Category, Listing, Merchant, Product
from db.session import get_session


@pytest.fixture
def client(session: Session):
    """TestClient whose request-scoped Session is the isolated fixture DB."""
    def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(session: Session) -> Session:
    """Two brands, two storage tiers, one out-of-stock listing."""
    session.add(Category(slug="phones", name="Phones", parent_id=None, sort_order=0))
    session.commit()
    jumia = Merchant(slug="jumia", name="Jumia", base_url="https://jumia.co.ke")
    kilimall = Merchant(slug="kilimall", name="Kilimall", base_url="https://kilimall.co.ke")
    session.add(jumia)
    session.add(kilimall)
    session.commit()

    products = [
        Product(
            slug="samsung-a55-128",
            canonical_key="samsung|a55|128|8",
            brand="samsung",
            model="a55",
            title="Samsung Galaxy A55 128GB",
            category_slug="phones",
            specs={"storage_gb": 128, "ram_gb": 8},
        ),
        Product(
            slug="samsung-a55-256",
            canonical_key="samsung|a55|256|8",
            brand="samsung",
            model="a55",
            title="Samsung Galaxy A55 256GB",
            category_slug="phones",
            specs={"storage_gb": 256, "ram_gb": 8},
        ),
        Product(
            slug="xiaomi-note13-128",
            canonical_key="xiaomi|note-13|128|6",
            brand="xiaomi",
            model="redmi note 13",
            title="Redmi Note 13 128GB",
            category_slug="phones",
            specs={"storage_gb": 128, "ram_gb": 6},
        ),
        # Sold out everywhere. Same brand as the Redmi above and a storage
        # tier none of the facet tests select, so its presence can't shift
        # the brand options or any storage assertion — it exists purely to
        # prove out-of-stock products are dropped.
        Product(
            slug="xiaomi-note13-pro-512",
            canonical_key="xiaomi|note-13-pro|512|12",
            brand="xiaomi",
            model="redmi note 13 pro",
            title="Redmi Note 13 Pro 512GB",
            category_slug="phones",
            specs={"storage_gb": 512, "ram_gb": 12},
        ),
    ]
    for p in products:
        session.add(p)
    session.commit()

    now = datetime.utcnow()
    listings = [
        Listing(product_id=products[0].id, merchant_id=jumia.id,
                url="https://jumia.co.ke/1",
                title_on_merchant="Samsung Galaxy A55 128GB",
                price_kes=Decimal("38000"), in_stock=True, last_checked_at=now),
        Listing(product_id=products[1].id, merchant_id=jumia.id,
                url="https://jumia.co.ke/2",
                title_on_merchant="Samsung Galaxy A55 256GB",
                price_kes=Decimal("52000"), in_stock=True, last_checked_at=now),
        Listing(product_id=products[2].id, merchant_id=kilimall.id,
                url="https://kilimall.co.ke/1",
                title_on_merchant="Redmi Note 13 128GB",
                price_kes=Decimal("28000"), in_stock=True, last_checked_at=now),
        # Sold out everywhere. Category pages exclude it entirely (see
        # tests/test_category_live_offers_only.py); it lives here so the
        # facet tests below prove they filter on the facet and not on stock.
        Listing(product_id=products[3].id, merchant_id=kilimall.id,
                url="https://kilimall.co.ke/2",
                title_on_merchant="Redmi Note 13 Pro 512GB",
                price_kes=Decimal("31000"), in_stock=False, last_checked_at=now),
    ]
    for lst in listings:
        session.add(lst)
    session.commit()
    return session


def test_no_filters_returns_all_products(client: TestClient, seeded: Session):
    r = client.get("/c/phones")
    assert r.status_code == 200
    assert "Samsung Galaxy A55 128GB" in r.text
    assert "Samsung Galaxy A55 256GB" in r.text
    assert "Redmi Note 13 128GB" in r.text


def test_brand_facet_narrows_result_set(client: TestClient, seeded: Session):
    r = client.get("/c/phones?brand=xiaomi")
    assert r.status_code == 200
    assert "Redmi Note 13 128GB" in r.text
    assert "Samsung Galaxy A55 128GB" not in r.text
    assert "Samsung Galaxy A55 256GB" not in r.text


def test_json_storage_facet_matches_via_dialect_bridge(
    client: TestClient, seeded: Session
):
    """Guards against the astext-attribute bug — this is the exact query
    pattern that 500'd before we added the SQLite/Postgres helper."""
    r = client.get("/c/phones?storage=256")
    assert r.status_code == 200
    assert "Samsung Galaxy A55 256GB" in r.text
    assert "Samsung Galaxy A55 128GB" not in r.text
    assert "Redmi Note 13 128GB" not in r.text


def test_price_max_range_facet_filters_on_aggregate(
    client: TestClient, seeded: Session
):
    r = client.get("/c/phones?price_max=40000")
    assert r.status_code == 200
    assert "Samsung Galaxy A55 128GB" in r.text  # 38k → in
    assert "Redmi Note 13 128GB" in r.text  # 28k → in
    assert "Samsung Galaxy A55 256GB" not in r.text  # 52k → out


def test_out_of_stock_products_are_always_dropped(
    client: TestClient, seeded: Session
):
    """No longer opt-in. This was `?in_stock=1` until 2026-08-25; the facet
    is gone and the behaviour is unconditional, so the bare URL must drop
    the sold-out product too."""
    r = client.get("/c/phones")
    assert r.status_code == 200
    assert "Samsung Galaxy A55 128GB" in r.text
    assert "Redmi Note 13 Pro 512GB" not in r.text


def test_stale_in_stock_query_param_is_harmless(
    client: TestClient, seeded: Session
):
    """Bookmarked ?in_stock=1 links must still render, just without effect."""
    r = client.get("/c/phones?in_stock=1")
    assert r.status_code == 200
    assert "Samsung Galaxy A55 128GB" in r.text
    assert "Redmi Note 13 Pro 512GB" not in r.text


def test_multiple_enum_values_are_or_matched(
    client: TestClient, seeded: Session
):
    """Multi-select — storage=128 OR storage=256 keeps both Samsungs plus
    the Redmi (which is 128)."""
    r = client.get("/c/phones?storage=128&storage=256")
    assert r.status_code == 200
    assert "Samsung Galaxy A55 128GB" in r.text
    assert "Samsung Galaxy A55 256GB" in r.text
    assert "Redmi Note 13 128GB" in r.text


def test_facet_sidebar_renders_available_brand_options(
    client: TestClient, seeded: Session
):
    """The sidebar must list both seeded brands as checkboxes."""
    r = client.get("/c/phones")
    assert r.status_code == 200
    # Brand values appear in the checkbox labels.
    assert 'value="samsung"' in r.text
    assert 'value="xiaomi"' in r.text
    # Universal facets always render.
    assert "Max price (KSh)" in r.text
    # "In stock only" is deliberately absent: category pages filter to
    # in-stock unconditionally, so the facet could only ever be a no-op.
    assert "In stock only" not in r.text
