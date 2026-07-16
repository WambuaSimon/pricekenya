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
    assert "0 listings" in str(exc.value) or "0 " in str(exc.value)


def test_severe_drop_raises() -> None:
    """A ~70% drop still trips the guard."""
    with pytest.raises(ScraperYieldTooLow):
        _assert_yield_healthy(
            merchant_slug="jumia", prior_count=200, yielded_count=40
        )


def test_modest_drop_within_threshold_is_accepted() -> None:
    """40% drop under the 50% ceiling — likely a seasonal inventory shift,
    NOT a scraper failure. Don't page the operator over it."""
    _assert_yield_healthy(
        merchant_slug="jumia", prior_count=100, yielded_count=60
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


def test_boundary_at_exact_threshold() -> None:
    """Exactly half of prior_count should NOT raise — the threshold is
    'less than half remains', not 'at most half remains'."""
    # prior=100, threshold=int(100 * 0.5)=50. yielded=50 passes.
    _assert_yield_healthy(
        merchant_slug="edge-ke", prior_count=100, yielded_count=50
    )
    # yielded=49 fails.
    with pytest.raises(ScraperYieldTooLow):
        _assert_yield_healthy(
            merchant_slug="edge-ke", prior_count=100, yielded_count=49
        )
