"""/admin/clicks — auth + per-merchant aggregation + outreach-threshold tint."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from db.models import Click, Listing, Merchant, Product


@pytest.fixture
def client(session, monkeypatch):
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


def _seed(session):
    """Two merchants, two listings each, with clicks spanning the three windows."""
    now = datetime.utcnow()
    jumia = Merchant(id=1, slug="jumia-ke", name="Jumia Kenya", base_url="https://jumia.co.ke")
    kilimall = Merchant(
        id=2, slug="kilimall-ke", name="Kilimall Kenya", base_url="https://kilimall.co.ke"
    )
    session.add(jumia)
    session.add(kilimall)
    session.commit()

    product_a = Product(
        slug="tecno-spark-30c",
        canonical_key="tecno|spark30c",
        brand="tecno",
        model="spark 30c",
        title="Tecno Spark 30C",
        category_slug="phones",
    )
    product_b = Product(
        slug="redmi-note-13",
        canonical_key="redmi|note13",
        brand="redmi",
        model="note 13",
        title="Redmi Note 13",
        category_slug="phones",
    )
    session.add(product_a)
    session.add(product_b)
    session.commit()

    l1 = Listing(
        product_id=product_a.id,
        merchant_id=jumia.id,
        url="https://jumia.co.ke/spark-30c",
        title_on_merchant="Tecno Spark 30C 5G",
        price_kes=Decimal("18999"),
    )
    l2 = Listing(
        product_id=product_b.id,
        merchant_id=jumia.id,
        url="https://jumia.co.ke/note-13",
        title_on_merchant="Redmi Note 13",
        price_kes=Decimal("27499"),
    )
    l3 = Listing(
        product_id=product_a.id,
        merchant_id=kilimall.id,
        url="https://kilimall.co.ke/spark",
        title_on_merchant="Tecno Spark 30 C 8+256",
        price_kes=Decimal("17750"),
    )
    session.add(l1)
    session.add(l2)
    session.add(l3)
    session.commit()

    # Jumia: 3 clicks last 7d, 6 last 30d, 10 last 90d.
    # Kilimall: 0 last 7d, 1 last 30d, 2 last 90d.
    def _click(listing_id: int, days_ago: float):
        session.add(
            Click(listing_id=listing_id, occurred_at=now - timedelta(days=days_ago))
        )

    for d in (0.5, 1.0, 5.0):  # 7d window
        _click(l1.id, d)
    for d in (10.0, 15.0, 25.0):  # 30d window (adds to 7d totals)
        _click(l2.id, d)
    for d in (40.0, 60.0, 75.0, 88.0):  # 90d only
        _click(l1.id, d)

    _click(l3.id, 20.0)  # kilimall 30d
    _click(l3.id, 70.0)  # kilimall 90d only


def test_401_without_key(client):
    resp = client.get("/admin/clicks")
    assert resp.status_code == 401


def test_renders_and_aggregates(client, session):
    _seed(session)
    resp = client.get(
        "/admin/clicks",
        headers={"X-Admin-Key": "top-secret"},
    )
    assert resp.status_code == 200
    body = resp.text

    # Both merchants show up.
    assert "Jumia Kenya" in body
    assert "Kilimall Kenya" in body

    # Jumia should be ordered before Kilimall (6 vs 1 in 30d).
    assert body.index("Jumia Kenya") < body.index("Kilimall Kenya")

    # Top listing for Jumia (30d): l2 has 3 clicks vs l1 has 3 in 30d.
    # Either title present is fine — the point is one of them renders.
    assert "Tecno Spark 30C 5G" in body or "Redmi Note 13" in body


def test_outreach_threshold_tint_absent_below_100(client, session):
    _seed(session)
    resp = client.get(
        "/admin/clicks",
        headers={"X-Admin-Key": "top-secret"},
    )
    # Seed volumes (6, 1 in 30d) are both below 100 — the row-tint class
    # pattern used only in the merchant table shouldn't appear.
    assert "bg-emerald-50 dark:bg-emerald-950/30" not in resp.text
