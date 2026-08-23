"""scripts/rebuild_sitemap refuses to publish a non-production BASE_URL.

On 2026-08-22 this script was run from a laptop with no BASE_URL set. It
inherited `http://localhost:8000` from the local .env and published 1,377
localhost URLs to the production sitemap, live for about a minute. Nothing
errored — every layer did exactly what it was told.

The scheduled workflow passes BASE_URL explicitly and was never at risk.
This guard is for the manual run, which is the case with no review step.
"""

from __future__ import annotations

import pytest

from scripts.rebuild_sitemap import UnsafeBaseUrl, _assert_safe_base_url


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8000",
        "https://localhost:8000",
        "http://127.0.0.1:8000",
        "https://127.0.0.1",
        "http://[::1]:8000",
        "https://mymac.local",
        "http://www.pricekenya.co.ke",  # right host, plaintext
    ],
)
def test_unsafe_base_urls_are_refused(base_url):
    with pytest.raises(UnsafeBaseUrl):
        _assert_safe_base_url(base_url)


@pytest.mark.parametrize(
    "base_url",
    [
        "https://www.pricekenya.co.ke",
        "https://www.pricekenya.co.ke/",
        "https://pricekenya.co.ke",
        "https://staging.pricekenya.co.ke",
    ],
)
def test_production_base_urls_pass(base_url):
    _assert_safe_base_url(base_url)


def test_dry_run_skips_the_guard(session, monkeypatch):
    """`--dry-run` must still work from a laptop — inspecting a build
    locally is the whole point, and it writes nothing."""
    from app import config
    from scripts import rebuild_sitemap

    monkeypatch.setattr(config.settings, "base_url", "http://localhost:8000")
    count = rebuild_sitemap.rebuild(session, dry_run=True)
    assert count >= 0


def test_real_run_refuses_and_writes_nothing(session, monkeypatch):
    from app import config
    from db.models import CachedSitemap
    from scripts import rebuild_sitemap

    monkeypatch.setattr(config.settings, "base_url", "http://localhost:8000")
    with pytest.raises(UnsafeBaseUrl):
        rebuild_sitemap.rebuild(session)

    assert session.get(CachedSitemap, 1) is None, "guard fired but a row was written"
