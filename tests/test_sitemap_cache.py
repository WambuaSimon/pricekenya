"""Cache-first sitemap: first hit builds + writes CachedSitemap(id=1),
subsequent hits inside the TTL serve the row without re-running the
product/listing join. Once the TTL expires the next request regenerates.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from db.models import CachedSitemap
from db.session import engine


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts from an empty cache so we can measure cold-path
    behaviour deterministically."""
    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        if row:
            s.delete(row)
            s.commit()
    yield
    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        if row:
            s.delete(row)
            s.commit()


def test_first_hit_builds_and_persists_cache() -> None:
    c = TestClient(app)
    r = c.get("/sitemap.xml")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=3600, s-maxage=3600"
    assert "<urlset" in r.text
    assert "</urlset>" in r.text

    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        assert row is not None
        assert row.body == r.text
        assert row.url_count > 0


def test_second_hit_serves_from_cache() -> None:
    c = TestClient(app)
    first = c.get("/sitemap.xml")
    assert first.status_code == 200

    with Session(engine) as s:
        row_before = s.get(CachedSitemap, 1)
        original_generated_at = row_before.generated_at

    second = c.get("/sitemap.xml")
    assert second.status_code == 200
    assert second.text == first.text

    with Session(engine) as s:
        row_after = s.get(CachedSitemap, 1)
        # Cache hit means the timestamp didn't move.
        assert row_after.generated_at == original_generated_at


def test_stale_cache_gets_regenerated() -> None:
    c = TestClient(app)
    c.get("/sitemap.xml")

    # Force the cache to look ancient — beyond the 6-hour TTL.
    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        row.generated_at = datetime.utcnow() - timedelta(hours=12)
        s.add(row)
        s.commit()
        stale_generated_at = row.generated_at

    # Even a small sleep guarantees the new generated_at is monotonically later.
    time.sleep(0.05)

    c.get("/sitemap.xml")

    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        assert row.generated_at > stale_generated_at


def test_response_has_product_urls_and_lastmod() -> None:
    """Sanity: the cache path serves the same shape as the prior in-place
    generator. Failures here would mean the extracted _build_sitemap_xml
    diverged from the pre-refactor output."""
    c = TestClient(app)
    r = c.get("/sitemap.xml")
    assert r.status_code == 200
    text = r.text
    # Standard header
    assert 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"' in text
    # Image extension
    assert "xmlns:image" in text
    # At least one product URL
    assert "/p/" in text
    # At least one lastmod
    assert "<lastmod>" in text
