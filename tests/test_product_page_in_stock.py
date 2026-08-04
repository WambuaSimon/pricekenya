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
from sqlmodel import select

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


def test_single_offer_product_has_noindex(client, session):
    """Single-offer products are noindex,follow so Google stops wasting crawl
    budget on functional-redirect pages. Matches the sitemap MIN_OFFERS=2
    prune."""
    session.add(Merchant(id=1, slug="jumia", name="Jumia", base_url="https://x"))
    session.commit()
    product = Product(
        slug="single-offer",
        canonical_key="single|offer",
        brand="test",
        model="one",
        title="One Offer Only",
        category_slug="phones",
    )
    session.add(product)
    session.commit()
    session.add(
        Listing(
            product_id=product.id,
            merchant_id=1,
            url="https://x/one",
            title_on_merchant="One",
            price_kes=Decimal("10000"),
            in_stock=True,
        )
    )
    session.commit()

    resp = client.get(f"/p/{product.slug}")
    assert resp.status_code == 200
    assert '<meta name="robots" content="noindex,follow">' in resp.text


def test_multi_offer_product_is_indexable(client, session):
    """2+ live offers = worth indexing; no robots meta emitted."""
    slug = _seed_product_with_mixed_offers(session)
    # Add a second in-stock offer so we have 2 live.
    product = session.exec(select(Product).where(Product.slug == slug)).first()
    session.add(
        Listing(
            product_id=product.id,
            merchant_id=1,
            url="https://jumia.co.ke/live-2",
            title_on_merchant="Test Phone (Second Live at Jumia)",
            price_kes=Decimal("18500"),
            in_stock=True,
        )
    )
    session.commit()

    resp = client.get(f"/p/{slug}")
    assert resp.status_code == 200
    assert '<meta name="robots" content="noindex' not in resp.text


def test_zero_offer_product_has_noindex(client, session):
    """Product with only sold-out offers gets noindexed AND shows the empty
    state — better than 404 for SEO (URL can come back if a merchant
    restocks) but no reason to index a dead page."""
    session.add(Merchant(id=1, slug="badili", name="Badili", base_url="https://x"))
    session.commit()
    product = Product(
        slug="all-dead",
        canonical_key="alldead|x",
        brand="test",
        model="x",
        title="All Dead",
        category_slug="phones",
    )
    session.add(product)
    session.commit()
    session.add(
        Listing(
            product_id=product.id,
            merchant_id=1,
            url="https://x/y",
            title_on_merchant="Y",
            price_kes=Decimal("10000"),
            in_stock=False,
        )
    )
    session.commit()

    resp = client.get(f"/p/{product.slug}")
    assert resp.status_code == 200
    assert '<meta name="robots" content="noindex,follow">' in resp.text


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
