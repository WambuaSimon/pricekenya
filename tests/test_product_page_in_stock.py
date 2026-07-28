"""Product page hides out-of-stock offers.

Regression guard for the 2026-07-28 Shopify fix: merchants sometimes
scrape products with variants[0].available=False (Badili, Zentech etc.
mark sold-out refurbs/discontinued lines that way). The Listing row
keeps in_stock=False, and product_detail must filter them out so
shoppers don't click through to a dead merchant page.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from db.models import Listing, Merchant, Product


@pytest.fixture
def client(session):
    from app.main import app
    from db.session import get_session

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _seed_product_with_mixed_offers(session):
    """One product, two merchants: one in-stock, one out-of-stock."""
    session.add(Merchant(id=1, slug="jumia", name="Jumia", base_url="https://jumia.co.ke"))
    session.add(Merchant(id=2, slug="badili", name="Badili", base_url="https://badili.ke"))
    session.commit()

    product = Product(
        slug="test-phone",
        canonical_key="test|phone",
        brand="test",
        model="phone",
        title="Test Phone",
        category_slug="phones",
    )
    session.add(product)
    session.commit()

    session.add(
        Listing(
            product_id=product.id,
            merchant_id=1,
            url="https://jumia.co.ke/live",
            title_on_merchant="Test Phone (Live at Jumia)",
            price_kes=Decimal("18000"),
            in_stock=True,
        )
    )
    session.add(
        Listing(
            product_id=product.id,
            merchant_id=2,
            url="https://badili.ke/sold-out",
            title_on_merchant="Test Phone (Sold Out at Badili)",
            price_kes=Decimal("15000"),
            in_stock=False,
        )
    )
    session.commit()
    return product.slug


def test_out_of_stock_offer_hidden(client, session):
    slug = _seed_product_with_mixed_offers(session)
    resp = client.get(f"/p/{slug}")
    assert resp.status_code == 200
    body = resp.text

    # In-stock offer renders.
    assert "Live at Jumia" in body
    # Out-of-stock offer must NOT render — either as an offer card or in
    # the JSON-LD availability list.
    assert "Sold Out at Badili" not in body


def test_all_offers_out_of_stock_renders_empty_state(client, session):
    """Product with only out-of-stock offers should still render (SEO — don't
    404 a page that had real offers once), but show the empty-offers state."""
    session.add(Merchant(id=1, slug="badili", name="Badili", base_url="https://badili.ke"))
    session.commit()
    product = Product(
        slug="only-sold-out",
        canonical_key="onlysoldout|x",
        brand="test",
        model="x",
        title="Only Sold Out",
        category_slug="phones",
    )
    session.add(product)
    session.commit()
    session.add(
        Listing(
            product_id=product.id,
            merchant_id=1,
            url="https://badili.ke/x",
            title_on_merchant="X",
            price_kes=Decimal("10000"),
            in_stock=False,
        )
    )
    session.commit()

    resp = client.get(f"/p/{product.slug}")
    assert resp.status_code == 200
    # Template's empty-offers copy — see product.html line ~218.
    assert "No offers right now" in resp.text
