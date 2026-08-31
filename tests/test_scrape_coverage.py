"""Staleness only means something broke when the merchant is meant to run.

Observed 2026-08-30: /admin/scrapes showed 11 red STALE rows, and every one
of them was expected. Four merchants were deprecated on purpose; seven were
Shopify stores still carrying full configs but excluded from the CI matrix
since 20-21 July. All 11 already had 0 in-stock listings, so nothing was
user-visible — but the dashboard could not say which rows deserved a look,
so none of them got one.

OPERATIONS.md had already noticed, telling readers the raw stale count
"overstates the problem by 5x; read it against the deprecation list, not on
its own". scrapers/coverage.py is that list, derived from the configs rather
than kept by hand so it cannot drift.
"""

from __future__ import annotations

import pytest

from scrapers.coverage import Coverage, classify, needs_attention


def test_woocommerce_merchant_is_active():
    assert classify("smartdevices-ke") is Coverage.ACTIVE


def test_custom_module_merchant_is_active():
    """Merchants with a bespoke scraper module, not a config entry."""
    assert classify("jumia-ke") is Coverage.ACTIVE
    assert classify("kilimall-ke") is Coverage.ACTIVE


def test_custom_module_slug_with_hyphens_resolves():
    """phone-place-ke -> scrapers/merchants/phone_place.py."""
    assert classify("phone-place-ke") is Coverage.ACTIVE


def test_shopify_merchant_is_parked_while_excluded_from_ci():
    """Configured and working, but no CI leg runs it — see the NOTE in
    .github/workflows/scrape.yml. Stale by decision, not by fault."""
    assert classify("digitalstore-ke") is Coverage.PARKED


def test_merchant_with_no_scraper_is_deprecated():
    """Removed from config entirely. Staleness is the designed end state."""
    assert classify("finetech-ke") is Coverage.DEPRECATED
    assert classify("zuka-ke") is Coverage.DEPRECATED


def test_deprecation_is_derived_not_hardcoded():
    """overtech-ke was deprecated in #33 by deleting its config entry, with
    no change here. Classification has to follow that automatically or it
    becomes another list to forget to update."""
    assert classify("overtech-ke") is Coverage.DEPRECATED


def test_unknown_slug_is_deprecated():
    assert classify("never-existed-ke") is Coverage.DEPRECATED


@pytest.mark.parametrize(
    "coverage,is_stale,expected",
    [
        (Coverage.ACTIVE, True, True),        # the only combination worth paging on
        (Coverage.ACTIVE, False, False),
        (Coverage.PARKED, True, False),       # stale by decision
        (Coverage.DEPRECATED, True, False),   # stale by design
        (Coverage.PARKED, False, False),
        (Coverage.DEPRECATED, False, False),
    ],
)
def test_needs_attention(coverage, is_stale, expected):
    assert needs_attention(coverage, is_stale) is expected


def test_health_row_separates_stale_from_broken(session):
    """The distinction the dashboard turns on, end to end."""
    from datetime import UTC, datetime, timedelta

    from scripts.scrape_health import MerchantHealth

    old = datetime.now(UTC) - timedelta(hours=500)
    parked = MerchantHealth(
        slug="digitalstore-ke", name="Digital Store", listing_count=1067,
        in_stock_count=0, last_checked_at=old, hours_since_last_check=500.0,
        coverage=Coverage.PARKED,
    )
    broken = MerchantHealth(
        slug="jumia-ke", name="Jumia", listing_count=2353,
        in_stock_count=0, last_checked_at=old, hours_since_last_check=500.0,
        coverage=Coverage.ACTIVE,
    )

    assert parked.is_stale(24.0) is True
    assert parked.needs_attention(24.0) is False, "parked staleness is not an incident"

    assert broken.is_stale(24.0) is True
    assert broken.needs_attention(24.0) is True, "an active merchant going stale is"


def test_to_row_serialises_coverage_for_json():
    """`scrape_health --json` feeds other tooling; an Enum would not encode."""
    from scripts.scrape_health import MerchantHealth

    row = MerchantHealth(
        slug="x-ke", name="X", listing_count=0, in_stock_count=0,
        last_checked_at=None, hours_since_last_check=None,
        coverage=Coverage.PARKED,
    ).to_row()
    assert row["coverage"] == "parked"
