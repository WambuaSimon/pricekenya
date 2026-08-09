"""noindex,follow on thin/duplicative surfaces beyond product pages.

Extends the treatment PR #7 gave to single-offer product pages:
- /search — always noindex (unbounded ?q= URL space)
- /c/<slug>?filter=… — noindex any filtered variant
- /c/<slug>?page=N (N>1) — noindex paginated variants
- /c/<slug> with 0 matching products — noindex empty
- /c/<slug> base URL with results — INDEXED (that's where category SEO lives)
"""

from __future__ import annotations

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


def _seed_category_with_products(session, n: int = 3):
    """Category tree plus N phone products with one listing each."""
    session.add(Category(id=1, slug="electronics", name="Electronics",
                         parent_id=None, sort_order=1))
    session.add(Category(id=2, slug="phones-tablets-accessories",
                         name="Phones", parent_id=1, sort_order=1))
    session.add(Category(id=3, slug="phones", name="Phones",
                         parent_id=2, sort_order=1))
    session.add(Merchant(id=1, slug="jumia", name="Jumia",
                        base_url="https://jumia.co.ke"))
    session.commit()

    for i in range(n):
        p = Product(
            slug=f"phone-{i}",
            canonical_key=f"brand|model-{i}",
            brand="samsung",
            model=f"model-{i}",
            title=f"Samsung Model {i}",
            category_slug="phones",
        )
        session.add(p)
    session.commit()

    for i in range(n):
        p = session.exec(
            __import__("sqlmodel").select(Product).where(Product.slug == f"phone-{i}")
        ).first()
        session.add(Listing(
            product_id=p.id, merchant_id=1,
            url=f"https://x/{i}", title_on_merchant=f"M{i}",
            price_kes=Decimal(str(10000 + i * 1000)), in_stock=True,
        ))
    session.commit()


# ---------------------------------------------------------------------------
# /search
# ---------------------------------------------------------------------------


def test_search_bare_is_noindexed(client):
    """No query = duplicative-of-home. Should not compete for indexing."""
    resp = client.get("/search")
    assert resp.status_code == 200
    assert NOINDEX_META in resp.text


def test_search_with_query_is_noindexed(client, session):
    """Even a query with real results — /search shouldn't grow the URL
    space in Google's index."""
    _seed_category_with_products(session, n=3)
    resp = client.get("/search?q=samsung")
    assert resp.status_code == 200
    assert NOINDEX_META in resp.text


def test_search_empty_results_is_noindexed(client):
    """No results = thin page, definitely noindex."""
    resp = client.get("/search?q=this-will-never-match-anything")
    assert resp.status_code == 200
    assert NOINDEX_META in resp.text


# ---------------------------------------------------------------------------
# /c/<slug>
# ---------------------------------------------------------------------------


def test_category_base_url_is_indexable(client, session):
    """Base /c/phones with products stays index-eligible — this is where
    category-level SEO ('phones price in Kenya', etc.) lives."""
    _seed_category_with_products(session, n=3)
    resp = client.get("/c/phones")
    assert resp.status_code == 200
    assert NOINDEX_META not in resp.text


def test_category_with_filter_is_noindexed(client, session):
    """?brand=samsung and other filter facets fragment ranking signal
    across combinatorial URL space. Noindex to preserve equity on base."""
    _seed_category_with_products(session, n=3)
    resp = client.get("/c/phones?brand=samsung")
    assert resp.status_code == 200
    assert NOINDEX_META in resp.text


def test_category_page_two_is_noindexed(client, session):
    """Paginated views duplicate base ranking signal — noindex. Seed
    enough products (PAGE_SIZE=48) that page=2 is a real page and not
    clamped to page 1."""
    _seed_category_with_products(session, n=60)
    resp = client.get("/c/phones?page=2")
    assert resp.status_code == 200
    assert NOINDEX_META in resp.text


def test_category_with_zero_products_is_noindexed(client, session):
    """Category exists in taxonomy but has no products (yet or ever).
    Empty = thin = noindex."""
    session.add(Category(id=1, slug="electronics", name="Electronics",
                         parent_id=None, sort_order=1))
    session.add(Category(id=2, slug="phones-tablets-accessories",
                         name="Phones", parent_id=1, sort_order=1))
    session.add(Category(id=3, slug="phones", name="Phones",
                         parent_id=2, sort_order=1))
    session.commit()

    resp = client.get("/c/phones")
    assert resp.status_code == 200
    assert NOINDEX_META in resp.text
