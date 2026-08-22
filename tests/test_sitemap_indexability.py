"""The sitemap and the product page must agree on what is indexable.

They didn't, and nothing caught it. `app/routes/meta.py` counted every
Listing on a product; `product.html` counted only the in-stock offers
`app/routes/products.py` had already filtered to. A comment in the
template asserted the two matched. With 47% of listings out of stock the
gap reached 1,175 of 2,504 advertised product URLs (46.9%) — every one a
URL the sitemap asked Google to crawl and the page then refused to let it
index.

The rule now lives in app/indexing.py in two forms — a per-page boolean
and an aggregate SQL predicate. This module is the guard that they stay
equivalent: the parametrised case below builds each scenario in the DB,
renders the real product page, runs the real sitemap builder, and asserts
neither can say "index me" while the other says otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from db.models import Category, Listing, Merchant, Product

NOINDEX_META = '<meta name="robots" content="noindex,follow">'


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


def _seed(session, offers: list[tuple[int, bool]]) -> str:
    """Create one product with `offers` as (merchant_id, in_stock) pairs.

    Returns the product slug. Product carries an image_url and fresh
    timestamps so the sitemap's other two filters never confound the
    result — this module is only about the merchant-count rule.
    """
    session.add(Category(id=1, slug="phones", name="Phones",
                         parent_id=None, sort_order=1))
    for mid in {m for m, _ in offers}:
        session.add(Merchant(id=mid, slug=f"m{mid}", name=f"Merchant {mid}",
                             base_url=f"https://m{mid}.example"))
    product = Product(
        slug="test-product",
        canonical_key="brand|model",
        brand="samsung",
        model="model",
        title="Samsung Test Product",
        category_slug="phones",
        image_url="https://example.com/img.jpg",
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    for i, (merchant_id, in_stock) in enumerate(offers):
        session.add(
            Listing(
                product_id=product.id,
                merchant_id=merchant_id,
                url=f"https://m{merchant_id}.example/p/{i}",
                title_on_merchant="Samsung Test Product",
                price_kes=Decimal("10000"),
                in_stock=in_stock,
                last_checked_at=datetime.now(UTC).replace(tzinfo=None),
            )
        )
    session.commit()
    return product.slug


def _sitemap_has(session, slug: str) -> bool:
    from app.routes.meta import _build_sitemap_xml

    body, _ = _build_sitemap_xml(session)
    return f"/p/{slug}<" in body or f"/p/{slug}</loc>" in body


@pytest.mark.parametrize(
    "offers,expected_indexable,why",
    [
        ([(1, True), (2, True)], True,
         "two merchants, both live — a real comparison"),
        ([(1, True)], False,
         "one merchant is a redirect, not a comparison"),
        ([], False,
         "no offers at all — a dead page"),
        ([(1, False), (2, False)], False,
         "two merchants but both sold out: the page renders no offers. "
         "This is the exact case the old sitemap query got wrong — it "
         "counted the listings and advertised the URL anyway"),
        ([(1, True), (2, False)], False,
         "only one live merchant once the sold-out one is dropped"),
        ([(1, True), (1, True)], False,
         "two live listings from ONE merchant is a duplicate SKU, not a "
         "comparison — distinct-merchant rule rejects it"),
    ],
)
def test_sitemap_and_page_agree(session, client, offers, expected_indexable, why):
    slug = _seed(session, offers)

    resp = client.get(f"/p/{slug}")
    assert resp.status_code == 200
    page_says_indexable = NOINDEX_META not in resp.text

    assert page_says_indexable is expected_indexable, why
    assert _sitemap_has(session, slug) is expected_indexable, why
    assert page_says_indexable is _sitemap_has(session, slug), (
        "sitemap and product page disagree — this is the 2026-08-22 bug"
    )


def test_empty_categories_are_not_advertised(session):
    """A category with no products anywhere in its subtree is noindex when
    rendered (categories.py: `total_rows == 0`), so it must not be in the
    sitemap either. Seven of 46 were, before this."""
    from app.routes.meta import _build_sitemap_xml

    session.add(Category(id=1, slug="electronics", name="Electronics",
                         parent_id=None, sort_order=1))
    session.add(Category(id=2, slug="phones", name="Phones",
                         parent_id=1, sort_order=2))
    session.add(Category(id=3, slug="toilets", name="Toilets",
                         parent_id=None, sort_order=3))
    session.add(Merchant(id=1, slug="m1", name="M1",
                         base_url="https://m1.example"))
    session.add(Product(
        slug="a-phone", canonical_key="b|m", brand="b", model="m",
        title="A Phone", category_slug="phones",
        image_url="https://example.com/i.jpg",
    ))
    session.commit()

    body, _ = _build_sitemap_xml(session)

    assert "/c/phones<" in body or "/c/phones</loc>" in body
    # Structural parent of a category that HAS products stays in — its
    # landing page aggregates the subtree.
    assert "/c/electronics<" in body or "/c/electronics</loc>" in body
    assert "/c/toilets" not in body, "empty category advertised to Google"
