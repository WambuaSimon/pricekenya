"""Home-page rotation + category-diversity logic.

The pure helpers (`_time_bucket`, `_select_home_rows`) are tested in
isolation — the home-page route calls them but the interesting logic
is here.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from decimal import Decimal

from db.models import Product


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
