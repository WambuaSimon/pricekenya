"""/admin/merge-review auth + approve/reject flows.

Uses the shared in-memory sqlite session fixture. The FastAPI TestClient
depends on `get_session` returning the same session used to set up rows,
so we override the dependency for the app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from db.models import Listing, Merchant, Product, ProductMergeCandidate


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


def _seed_pair(session):
    session.add(
        Merchant(id=1, slug="jumia", name="Jumia", base_url="https://jumia.co.ke")
    )
    session.commit()

    src = Product(
        slug="src",
        canonical_key="src|key",
        brand="tecno",
        model="spark 30c",
        title="Tecno Spark 30C",
        category_slug="phones",
    )
    tgt = Product(
        slug="tgt",
        canonical_key="tgt|key",
        brand="tecno",
        model="spark 30c",
        title="Tecno Spark 30 C",
        category_slug="phones",
    )
    session.add(src)
    session.add(tgt)
    session.commit()

    session.add(
        Listing(
            product_id=src.id,
            merchant_id=1,
            url="https://x",
            title_on_merchant="src listing",
            price_kes=10000,
        )
    )
    session.add(
        ProductMergeCandidate(
            source_product_id=src.id,
            target_product_id=tgt.id,
            similarity=0.92,
            source_title="Tecno Spark 30C mystery",
        )
    )
    session.commit()
    return src.id, tgt.id


def test_401_without_key(client):
    resp = client.get("/admin/merge-review")
    assert resp.status_code == 401


def test_get_renders(client, session):
    _seed_pair(session)
    resp = client.get(
        "/admin/merge-review",
        headers={"X-Admin-Key": "top-secret"},
    )
    assert resp.status_code == 200
    assert "cosine similarity" in resp.text
    assert "Tecno Spark 30C" in resp.text


def test_approve_reparents_and_deletes_source(client, session):
    src_id, tgt_id = _seed_pair(session)
    cand = session.exec(select(ProductMergeCandidate)).first()

    resp = client.post(
        f"/admin/merge-review/{cand.id}/approve",
        headers={"X-Admin-Key": "top-secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    listings = session.exec(select(Listing)).all()
    assert len(listings) == 1
    assert listings[0].product_id == tgt_id
    assert session.get(Product, src_id) is None
    approved = session.exec(select(ProductMergeCandidate)).first()
    assert approved.status == "approved"


def test_reject_marks_status_only(client, session):
    src_id, tgt_id = _seed_pair(session)
    cand = session.exec(select(ProductMergeCandidate)).first()

    resp = client.post(
        f"/admin/merge-review/{cand.id}/reject",
        headers={"X-Admin-Key": "top-secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert session.get(Product, src_id) is not None
    assert session.get(Product, tgt_id) is not None
    rejected = session.exec(select(ProductMergeCandidate)).first()
    assert rejected.status == "rejected"
