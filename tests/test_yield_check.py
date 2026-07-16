"""Post-scrape row-count sanity check.

Guards against the failure mode we observed on xiaomi-ke on 2026-07-16:
a merchant rebuilt their site, our HTML selectors stopped matching,
the scraper silently yielded zero RawListings, ingest committed
nothing, CI stayed green, and the DB rotted for ~75 hours until a
human noticed on /admin/scrapes.

_assert_yield_healthy raises when yielded_count is far below the
merchant's prior listing count on file. The matrix leg exits non-zero
and the Telegram notification path fires.
"""

from __future__ import annotations

import pytest

from scrapers.ingest import ScraperYieldTooLow, _assert_yield_healthy


def test_zero_yield_on_established_merchant_raises() -> None:
    """The exact xiaomi-ke case — 66 listings on record, scraper yields 0."""
    with pytest.raises(ScraperYieldTooLow) as exc:
        _assert_yield_healthy(
            merchant_slug="xiaomi-ke", prior_count=66, yielded_count=0
        )
    # Error message must name the merchant so the Telegram / stderr
    # readout is immediately actionable.
    assert "xiaomi-ke" in str(exc.value)
    assert "ZERO" in str(exc.value)


def test_partial_yield_is_accepted() -> None:
    """Only literal zero yield fires — partial yields might just be
    a per-category scraper on a multi-category merchant (e.g. run_
    jumia_phones scrapes ONE of Jumia's ~20 categories, so 200 phone
    rows against a merchant total of 1600 is expected, not a failure).
    """
    # ~78% drop (Jumia phones scenario from 2026-07-16).
    _assert_yield_healthy(
        merchant_slug="jumia-ke", prior_count=1642, yielded_count=360
    )
    # 40% drop — legitimate seasonal shift.
    _assert_yield_healthy(
        merchant_slug="jumia", prior_count=100, yielded_count=60
    )
    # Even a severe 90% drop that isn't zero is accepted — the
    # /admin/scrapes dashboard surfaces the stale rows separately.
    _assert_yield_healthy(
        merchant_slug="jumia", prior_count=200, yielded_count=20
    )


def test_growth_is_accepted() -> None:
    """More rows than prior is fine — no upper bound."""
    _assert_yield_healthy(
        merchant_slug="jumia", prior_count=100, yielded_count=500
    )


def test_small_merchant_below_floor_skipped() -> None:
    """Merchants below the MIN_PRIOR floor are skipped so brand-new
    merchants (prior=0) don't false-alarm on their first run."""
    # 15 listings on record < 20 floor → no check even if yield is 0.
    _assert_yield_healthy(
        merchant_slug="newbie-ke", prior_count=15, yielded_count=0
    )
    _assert_yield_healthy(
        merchant_slug="newbie-ke", prior_count=0, yielded_count=0
    )


def test_one_yielded_row_is_enough() -> None:
    """Even a single row makes the guard sit quiet — the check is a
    hard-zero tripwire, not a bounds check on catalog completeness."""
    _assert_yield_healthy(
        merchant_slug="edge-ke", prior_count=1000, yielded_count=1
    )
