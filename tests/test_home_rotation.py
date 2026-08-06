"""Home-page rotation + category-diversity logic + featured comparison.

The pure helpers (`_time_bucket`, `_select_home_rows`, `_select_featured`)
are tested in isolation. `_fetch_featured_offers` + the end-to-end hero
render are covered by fixture-backed route tests at the bottom.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from db.models import Listing, Merchant, Product


def _mock_row(product_id: int, category: str, offer_count: int = 3):
    """Match the (Product, min_price, offer_count) tuple shape the home
    query returns."""
    p = Product(
        id=product_id,
        slug=f"slug-{product_id}",
        canonical_key=f"k|{product_id}",
        brand="brand",
        model=f"model-{product_id}",
        title=f"Product {product_id}",
        category_slug=category,
    )
    return (p, Decimal("10000"), offer_count)


def test_time_bucket_stable_within_window():
    """Two calls inside the same 6h window return the same seed."""
    from app.routes.pages import _time_bucket

    early = datetime(2026, 8, 6, 8, 0, 0)   # 08:00 → bucket floor 06:00 window
    later = datetime(2026, 8, 6, 11, 59, 0) # 11:59 → same 06:00 window
    assert _time_bucket(early) == _time_bucket(later)


def test_time_bucket_changes_across_window():
    """Crossing a 6h boundary changes the seed."""
    from app.routes.pages import _time_bucket

    before = datetime(2026, 8, 6, 11, 59, 0)  # bucket 06-12
    after = datetime(2026, 8, 6, 12, 0, 0)    # bucket 12-18
    assert _time_bucket(before) != _time_bucket(after)


def test_select_home_rows_caps_per_category():
    """No category should exceed max_per_category in the returned slice."""
    from app.routes.pages import _select_home_rows

    # Pool of 40 products across 4 categories, 10 each.
    pool = []
    for cat in ["phones", "tvs", "audio", "cooking"]:
        for _ in range(10):
            pool.append(_mock_row(product_id=len(pool) + 1, category=cat))

    rows = _select_home_rows(pool, bucket_seed=42, max_per_category=4, display=24)
    counts = Counter(row[0].category_slug for row in rows)
    assert all(v <= 4 for v in counts.values()), counts


def test_select_home_rows_deterministic_within_bucket():
    """Same seed → same order. Guards against accidentally introducing
    non-determinism (e.g. depending on dict iteration order)."""
    from app.routes.pages import _select_home_rows

    pool = [_mock_row(i, "phones") for i in range(1, 30)]
    rows_a = _select_home_rows(pool, bucket_seed=99, max_per_category=100, display=10)
    rows_b = _select_home_rows(pool, bucket_seed=99, max_per_category=100, display=10)
    assert [r[0].id for r in rows_a] == [r[0].id for r in rows_b]


def test_select_home_rows_changes_across_buckets():
    """Different seed → different order (with overwhelming probability
    for a pool of 30 shuffled by different seeds)."""
    from app.routes.pages import _select_home_rows

    pool = [_mock_row(i, "phones") for i in range(1, 30)]
    rows_a = _select_home_rows(pool, bucket_seed=1, max_per_category=100, display=10)
    rows_b = _select_home_rows(pool, bucket_seed=2, max_per_category=100, display=10)
    assert [r[0].id for r in rows_a] != [r[0].id for r in rows_b]


def test_select_home_rows_stops_at_display_limit():
    """Even with a large diverse pool, only `display` rows come back."""
    from app.routes.pages import _select_home_rows

    pool = []
    for cat in ["phones", "tvs", "audio", "cooking", "refrigerators",
                "laptops", "cameras", "inverters"]:
        for _ in range(20):
            pool.append(_mock_row(product_id=len(pool) + 1, category=cat))

    rows = _select_home_rows(pool, bucket_seed=7, max_per_category=4, display=24)
    assert len(rows) == 24


def test_select_home_rows_returns_less_when_pool_thin():
    """A pool smaller than display or bottle-necked by category cap
    returns fewer rows (rather than duplicating or erroring)."""
    from app.routes.pages import _select_home_rows

    # 10 phones, cap 4 per category → at most 4 rows come back
    # regardless of `display=24`.
    pool = [_mock_row(i, "phones") for i in range(1, 11)]
    rows = _select_home_rows(pool, bucket_seed=42, max_per_category=4, display=24)
    assert len(rows) == 4


def test_select_featured_rotates_within_top_slice():
    """Different buckets pick different featured products; same bucket
    returns the same one."""
    from app.routes.pages import _select_featured

    pool = [_mock_row(i, "phones") for i in range(1, 60)]
    a = _select_featured(pool, bucket_seed=0, slice_size=30)
    b = _select_featured(pool, bucket_seed=0, slice_size=30)
    c = _select_featured(pool, bucket_seed=1, slice_size=30)
    assert a[0].id == b[0].id
    assert a[0].id != c[0].id


def test_select_featured_stays_within_top_slice():
    """Even for a large bucket seed, we never dip below the top slice —
    the featured product should always be a comparison-worthy one."""
    from app.routes.pages import _select_featured

    pool = [_mock_row(i, "phones") for i in range(1, 100)]
    for seed in (0, 1, 29, 30, 100, 9999):
        featured = _select_featured(pool, bucket_seed=seed, slice_size=30)
        assert featured[0].id in {row[0].id for row in pool[:30]}


def test_select_featured_returns_none_on_empty_pool():
    from app.routes.pages import _select_featured
    assert _select_featured([], bucket_seed=0, slice_size=30) is None


# ---------------------------------------------------------------------------
# End-to-end: home route renders the head-to-head hero when data supports it.
# ---------------------------------------------------------------------------


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


def _seed_hero_ready_product(session):
    """One phone with three merchant offers — enough to trigger the
    head-to-head hero."""
    session.add(Merchant(id=1, slug="jumia", name="Jumia Kenya", base_url="https://jumia.co.ke"))
    session.add(Merchant(id=2, slug="kilimall", name="Kilimall Kenya", base_url="https://kilimall.co.ke"))
    session.add(Merchant(id=3, slug="phoneplace", name="Phone Place", base_url="https://phoneplacekenya.com"))
    session.commit()

    product = Product(
        slug="redmi-note-15",
        canonical_key="xiaomi|note-15",
        brand="xiaomi",
        model="note 15",
        title="Xiaomi Redmi Note 15 5G",
        category_slug="phones",
        image_url="https://example.com/note15.jpg",
    )
    session.add(product)
    session.commit()

    session.add(Listing(product_id=product.id, merchant_id=1, url="https://x/1",
                        title_on_merchant="Note 15", price_kes=Decimal("26200"), in_stock=True))
    session.add(Listing(product_id=product.id, merchant_id=2, url="https://x/2",
                        title_on_merchant="Note 15", price_kes=Decimal("24500"), in_stock=True))
    session.add(Listing(product_id=product.id, merchant_id=3, url="https://x/3",
                        title_on_merchant="Note 15", price_kes=Decimal("25800"), in_stock=True))
    session.commit()


def test_home_hero_renders_head_to_head(client, session):
    _seed_hero_ready_product(session)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text

    # Product title + all three merchant names appear in the hero.
    assert "Xiaomi Redmi Note 15 5G" in body
    assert "Jumia Kenya" in body
    assert "Kilimall Kenya" in body
    assert "Phone Place" in body

    # Cheapest badge shows on the winner (Kilimall @ 24,500).
    assert "Cheapest" in body

    # Savings line: max - min = 26,200 - 24,500 = 1,700 KSh (~6%).
    assert "Save" in body
    assert "1,700" in body


def test_home_hero_degrades_when_no_multi_offer_products(client, session):
    """Empty catalog → hero falls back to the generic tagline without
    crashing."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.text
    # No head-to-head content, but the page still renders the tagline.
    assert "who's cheapest" in body
    assert "Cheapest" not in body  # winner-badge string absent
