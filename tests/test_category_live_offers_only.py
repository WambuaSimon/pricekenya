"""Category pages count only offers a shopper can actually buy.

Until 2026-08-25 the category grid aggregated min_price and offer_count
over EVERY listing, while product_detail (app/routes/products.py) showed
only in-stock ones. Measured on production, 1,793 products advertised a
price from a merchant we had stopped scraping weeks earlier, and 1,477 of
those had no live offer behind them at all. The shopper saw
"KSh 18,500 · 3 offers", clicked, and got a higher price or "No offers
right now".

Same bug class as the sitemap/noindex mismatch fixed in #22: two surfaces
answering "what offers exist" differently, each plausible in isolation.
These tests pin every category-page figure to the in-stock rule so the
grid, the stat block, the product page and the sitemap cannot drift apart
again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from db.models import Category, Listing, Merchant, Product


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


def _seed(session):
    """One product, two merchants: a CHEAP dead offer and a live one.

    Mirrors the production shape — the dead merchant is cheaper, which is
    exactly why it won min() and surfaced on the card.
    """
    session.add(Category(id=1, slug="phones", name="Phones",
                         parent_id=None, sort_order=1))
    session.add(Merchant(id=1, slug="dead-shop", name="Dead Shop",
                         base_url="https://dead.example"))
    session.add(Merchant(id=2, slug="live-shop", name="Live Shop",
                         base_url="https://live.example"))
    product = Product(
        slug="test-phone", canonical_key="b|m", brand="samsung", model="m",
        title="Samsung Test Phone", category_slug="phones",
        image_url="https://example.com/i.jpg",
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    now = datetime.now(UTC).replace(tzinfo=None)
    session.add(Listing(
        product_id=product.id, merchant_id=1, url="https://dead.example/p",
        title_on_merchant="Samsung Test Phone", price_kes=Decimal("18500"),
        in_stock=False, last_checked_at=now,
    ))
    session.add(Listing(
        product_id=product.id, merchant_id=2, url="https://live.example/p",
        title_on_merchant="Samsung Test Phone", price_kes=Decimal("24000"),
        in_stock=True, last_checked_at=now,
    ))
    session.commit()
    return product


def test_card_price_excludes_dead_offers(client, session):
    """The card must show 24,000 (live) not 18,500 (dead)."""
    _seed(session)
    resp = client.get("/c/phones")
    assert resp.status_code == 200
    assert "24,000" in resp.text
    assert "18,500" not in resp.text, "category card advertised a dead offer's price"


def test_offer_count_excludes_dead_offers(client, session):
    """Two listings, one live: the card says 1 shop, not 2.

    Cards counted "offers" until the 2026-08 revamp and now count "shops";
    the number is what this test is about, not the noun.
    """
    _seed(session)
    resp = client.get("/c/phones")
    assert resp.status_code == 200
    assert "1 shop" in resp.text
    assert "2 shops" not in resp.text


def test_product_with_no_live_offer_is_not_listed(client, session):
    """A product whose every offer is dead must not appear at all. It has
    nothing to sell, and its product page already renders 'No offers right
    now'."""
    session.add(Category(id=1, slug="phones", name="Phones",
                         parent_id=None, sort_order=1))
    session.add(Merchant(id=1, slug="dead-shop", name="Dead Shop",
                         base_url="https://dead.example"))
    ghost = Product(
        slug="ghost-phone", canonical_key="b|g", brand="samsung", model="g",
        title="Ghost Phone", category_slug="phones",
    )
    session.add(ghost)
    session.commit()
    session.refresh(ghost)
    session.add(Listing(
        product_id=ghost.id, merchant_id=1, url="https://dead.example/g",
        title_on_merchant="Ghost Phone", price_kes=Decimal("9999"),
        in_stock=False,
        last_checked_at=datetime.now(UTC).replace(tzinfo=None),
    ))
    session.commit()

    resp = client.get("/c/phones")
    assert resp.status_code == 200
    assert "Ghost Phone" not in resp.text


def test_shop_count_excludes_merchants_with_nothing_in_stock(client, session):
    """The 'Shops' stat counts shops you can buy from today. Two merchants
    exist; only one has stock, so the figure is 1.

    Asserted against the meta description rather than the stat markup: it
    renders both counts in one sentence, so it pins product_count and
    merchant_count together and doesn't break when the stat block is
    restyled by the pending visual revamp.
    """
    _seed(session)
    resp = client.get("/c/phones")
    assert resp.status_code == 200
    assert "Compare 1 phones across 1 Kenyan merchants" in resp.text, (
        "expected 1 product / 1 shop; a 2 here means the dead merchant "
        "was counted"
    )


def test_in_stock_facet_is_gone(session):
    """The facet could only ever be a no-op once the base query filters
    unconditionally, and a control that does nothing is worse than none."""
    from app.facets import UNIVERSAL, facets_for

    assert all(f.key != "in_stock" for f in UNIVERSAL)
    assert all(f.key != "in_stock" for f in facets_for("phones"))


def test_stale_in_stock_url_is_ignored_not_an_error(client, session):
    """Bookmarked ?in_stock=1 URLs must keep working, just without effect."""
    _seed(session)
    resp = client.get("/c/phones?in_stock=1")
    assert resp.status_code == 200
    assert "24,000" in resp.text
