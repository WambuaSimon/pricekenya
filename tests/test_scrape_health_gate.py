"""A merchant can break without any scrape leg failing.

tclke-ke sat broken for 76 hours in silence. Its site had been rebuilt on a
JS platform, so every fetch returned 200 and parsed to zero cards — the leg
ran, yielded nothing, and exited 0. Nothing alerted:

  - `notify` keys off `needs.scrape.result == 'failure'`, and no leg failed.
  - ScraperYieldTooLow needs a leg to RUN and yield zero, which this did, but
    per-category callers opt out of that guard on purpose so a category a
    merchant genuinely does not stock cannot false-positive. From inside the
    leg, a whole-site rebuild is indistinguishable from an empty category.

The gate closes that by asking the database rather than the leg: is any
merchant we still expect to be scraping now stale? Parked and deprecated
merchants are stale by design and must never trip it, or the alert becomes
the same undifferentiated noise /admin/scrapes showed before #34.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scrapers.coverage import Coverage
from scripts.scrape_health import MerchantHealth


def _row(slug: str, hours: float | None, coverage: Coverage) -> MerchantHealth:
    return MerchantHealth(
        slug=slug, name=slug, listing_count=88, in_stock_count=0,
        last_checked_at=(datetime.now(UTC) - timedelta(hours=hours)) if hours else None,
        hours_since_last_check=hours, coverage=coverage,
    )


def _broken(rows, stale_hours=30.0):
    """What --fail-on-broken counts."""
    return [r for r in rows if r.needs_attention(stale_hours)]


def test_silent_yield_failure_is_caught():
    """The tclke-ke case: active, 76h stale, no leg ever failed."""
    assert _broken([_row("tclke-ke", 76.0, Coverage.ACTIVE)])


def test_parked_merchant_does_not_trip_the_gate():
    """1,019h stale and entirely expected — CI must stay green."""
    assert not _broken([_row("digitalstore-ke", 1019.0, Coverage.PARKED)])


def test_deprecated_merchant_does_not_trip_the_gate():
    assert not _broken([_row("finetech-ke", 626.0, Coverage.DEPRECATED)])


def test_healthy_merchant_does_not_trip_the_gate():
    assert not _broken([_row("jumia-ke", 4.0, Coverage.ACTIVE)])


def test_one_missed_cron_window_is_not_news():
    """The cron runs every 12h. A single missed window is noise; the gate
    runs at 30h so it takes two consecutive misses to fire."""
    assert not _broken([_row("jumia-ke", 13.0, Coverage.ACTIVE)])
    assert _broken([_row("jumia-ke", 31.0, Coverage.ACTIVE)])


def test_never_scraped_merchant_does_not_trip_the_gate():
    """hours_since_last_check is None for a merchant with zero listings.
    That is a config question, not a scraper regression, and must not
    page anyone at 3am."""
    assert not _broken([_row("sollatek-ke", None, Coverage.ACTIVE)])


def test_a_realistic_mixed_fleet_reports_only_the_broken_one():
    rows = [
        _row("jumia-ke", 4.0, Coverage.ACTIVE),
        _row("kilimall-ke", 6.0, Coverage.ACTIVE),
        _row("digitalstore-ke", 1019.0, Coverage.PARKED),
        _row("finetech-ke", 626.0, Coverage.DEPRECATED),
        _row("tclke-ke", 76.0, Coverage.ACTIVE),
    ]
    assert [r.slug for r in _broken(rows)] == ["tclke-ke"]


@pytest.mark.parametrize("flag", ["--fail-on-broken", "--stale-hours"])
def test_cli_still_accepts_the_flags_ci_invokes(flag):
    """.github/workflows/scrape.yml calls both by name. Renaming either
    without updating the workflow would leave the gate silently unarmed —
    argparse exits 2 on an unknown flag, and the job would fail for the
    wrong reason."""
    import inspect

    import scripts.scrape_health as sh

    assert flag in inspect.getsource(sh.main)


def test_workflow_invokes_the_gate():
    """The gate is only worth anything if CI actually runs it."""
    import pathlib

    wf = pathlib.Path(".github/workflows/scrape.yml").read_text()
    assert "--fail-on-broken" in wf
    assert "scripts.scrape_health" in wf
