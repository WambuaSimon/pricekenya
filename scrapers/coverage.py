"""Which merchants are actually being scraped, and which only look broken.

`/admin/scrapes` and `scripts.scrape_health` flag any merchant whose newest
listing is older than the threshold. That is the right measurement but it
answers the wrong question on its own: a merchant nobody scrapes any more is
stale by design, and rendering it in the same red as a merchant that broke
yesterday buries the signal.

Observed 2026-08-30: 11 merchants flagged stale, all with 0 in-stock
listings. Four were deprecated on purpose. The other seven were Shopify
stores still carrying full configs but silently excluded from the CI matrix,
un-scraped since 20-21 July — 2,417 listings, roughly a quarter of the
catalog, sitting invisible. Nothing alerted, because ScraperYieldTooLow only
fires when a leg RUNS and yields zero, and these legs never ran at all.

OPERATIONS.md already told readers to "read it against the deprecation list,
not on its own". This module is that list, derived rather than maintained by
hand.
"""

from __future__ import annotations

import pkgutil
from enum import StrEnum


class Coverage(StrEnum):
    """Why a merchant's listings are or aren't being refreshed."""

    ACTIVE = "active"
    #: Configured, but deliberately not run by CI. Staleness is expected and
    #: is not a scraper fault — it is a decision waiting to be revisited.
    PARKED = "parked"
    #: No scraper config and no module. Staleness is the designed end state.
    DEPRECATED = "deprecated"


#: Every Shopify target is excluded from the CI matrix: GitHub's Azure IPs
#: get HTTP 429 from Shopify's edge, and Render's Frankfurt IP is rate
#: limited too. Deferred pending a residential proxy — see the NOTE in
#: .github/workflows/scrape.yml and OPERATIONS.md §8g.
#:
#: Kept as a flag rather than parsed out of the workflow YAML, which would
#: couple this to CI's file layout. If Shopify goes back into the matrix,
#: flip this to False and `parked` merchants become `active` again.
SHOPIFY_RUNS_IN_CI = False


def _custom_module_stems() -> set[str]:
    """Module stems under scrapers/merchants/, e.g. {"jumia", "kilimall"}."""
    import scrapers.merchants as merchants_pkg

    return {m.name for m in pkgutil.iter_modules(merchants_pkg.__path__)}


def classify(slug: str) -> Coverage:
    """Return why `slug` is or isn't being refreshed.

    Derived from the scraper configs rather than a hand-kept list, so a
    merchant removed from config is reported as deprecated automatically
    and cannot drift out of sync with reality.
    """
    from scrapers.config.shopify_merchants import SHOPIFY_MERCHANTS
    from scrapers.config.wc_merchants import WC_MERCHANTS

    if slug in SHOPIFY_MERCHANTS:
        return Coverage.ACTIVE if SHOPIFY_RUNS_IN_CI else Coverage.PARKED
    if slug in WC_MERCHANTS:
        return Coverage.ACTIVE
    # Custom per-merchant scrapers are named after the slug minus its
    # country suffix, with hyphens as underscores: jumia-ke -> jumia,
    # phone-place-ke -> phone_place.
    stem = slug.removesuffix("-ke").replace("-", "_")
    if stem in _custom_module_stems():
        return Coverage.ACTIVE
    return Coverage.DEPRECATED


def needs_attention(coverage: Coverage, is_stale: bool) -> bool:
    """True when staleness on this merchant is a fault worth chasing.

    A parked or deprecated merchant being stale is the expected outcome, not
    an incident. Only an ACTIVE merchant going stale means something broke.
    """
    return is_stale and coverage is Coverage.ACTIVE
