"""Read-only sitemap route: it serves CachedSitemap(id=1) and, once a row
exists, never rebuilds on a request no matter how stale the row is.

Rebuilds belong to .github/workflows/sitemap.yml (03:15 / 15:15 UTC) and
scripts/rebuild_sitemap.py. Before 2026-08-22 this route regenerated
inline once the row passed a 24h TTL, which meant Googlebot usually paid
a GROUP BY over every Listing plus ~640KB of serialization on a 0.5-CPU
dyno, and every request arriving after the TTL lapsed raced the others to
write the same single row. Both are candidates for the 31 "Server error
(5xx)" pages Search Console reports.

The only surviving build path is a genuinely cold DB with no row at all.
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
    assert r.headers.get("cache-control") == "public, max-age=21600, s-maxage=21600"
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


def test_stale_cache_is_served_not_regenerated() -> None:
    """A stale row is served AS-IS. Yesterday's sitemap beats a timeout,
    and the cron replaces it within 12h.

    This asserts the opposite of what it did before 2026-08-22 — the
    regeneration it used to require is exactly the request-path build that
    had Googlebot paying for the join.
    """
    c = TestClient(app)
    c.get("/sitemap.xml")

    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        row.body = "<urlset>SENTINEL</urlset>"
        row.generated_at = datetime.utcnow() - timedelta(days=30)
        s.add(row)
        s.commit()
        stale_generated_at = row.generated_at

    time.sleep(0.05)
    resp = c.get("/sitemap.xml")

    assert resp.status_code == 200
    assert "SENTINEL" in resp.text, "route rebuilt instead of serving the row"

    with Session(engine) as s:
        row = s.get(CachedSitemap, 1)
        assert row.generated_at == stale_generated_at, "route wrote on a read"
        assert row.body == "<urlset>SENTINEL</urlset>"


def test_cold_db_still_builds_once() -> None:
    """No row at all — a fresh deploy must not serve nothing until the
    next cron fires. This is the one remaining inline build."""
    with Session(engine) as s:
        assert s.get(CachedSitemap, 1) is None

    resp = TestClient(app).get("/sitemap.xml")
    assert resp.status_code == 200
    assert "<urlset" in resp.text

    with Session(engine) as s:
        assert s.get(CachedSitemap, 1) is not None


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
