"""Validation rules for the product-image cache.

The cache exists because hotlinks fail (OPERATIONS.md 8ag). The failure mode
it must not introduce is caching an outage: a blocked merchant commonly
answers with 200 and an `image/*` Content-Type while the body is an HTML
challenge page. Trusting that header would freeze the broken state into our
own bucket, where no later scrape could fix it. So content is sniffed from
magic bytes and the header is only a last resort.

No network and no R2 here — every test drives the pure validation path.
"""

from __future__ import annotations

import httpx
import pytest

from app.context import product_image
from scrapers.common.image_cache import (
    MAX_BYTES,
    MIN_BYTES,
    _sniff_ext,
    cache_enabled,
    cache_image,
)

JPEG = b"\xff\xd8\xff" + b"\x00" * 2000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 2000
GIF = b"GIF89a" + b"\x00" * 2000
HTML = b"<!DOCTYPE html><html><head><title>Just a moment...</title>" + b" " * 2000


@pytest.mark.parametrize(
    "body,ctype,expected",
    [
        (JPEG, "image/jpeg", "jpg"),
        (PNG, "image/png", "png"),
        (WEBP, "image/webp", "webp"),
        (GIF, "image/gif", "gif"),
        # Magic bytes beat a lying header, in both directions.
        (JPEG, "text/html", "jpg"),
        (PNG, "application/octet-stream", "png"),
    ],
)
def test_sniff_detects_real_images(body, ctype, expected):
    assert _sniff_ext(body, ctype) == expected


def test_cloudflare_challenge_page_is_refused_despite_image_content_type():
    """The exact shape phoneplacekenya.com returns. Caching this would turn a
    recoverable outage into a permanent one."""
    assert _sniff_ext(HTML, "image/jpeg") is None


def test_unknown_type_with_no_magic_is_refused():
    assert _sniff_ext(b"%PDF-1.4" + b"\x00" * 100, "application/pdf") is None
    assert _sniff_ext(b"<svg xmlns=", "image/svg+xml") is None


def test_header_is_the_last_resort_not_the_first():
    """A body we can't sniff but a header we allow is accepted — some CDNs
    serve AVIF/WebP variants we don't have magic for."""
    assert _sniff_ext(b"\x00" * 50, "image/webp") == "webp"


@pytest.fixture()
def _r2(monkeypatch):
    from app.config import settings

    for k, v in [
        ("r2_account_id", "acct"),
        ("r2_access_key_id", "key"),
        ("r2_secret_access_key", "secret"),
        ("r2_bucket", "bucket"),
        ("r2_public_base_url", "https://img.pricekenya.co.ke"),
    ]:
        monkeypatch.setattr(settings, k, v)
    yield


def test_cache_disabled_without_credentials(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "r2_account_id", "")
    assert cache_enabled() is False


def test_cache_enabled_with_all_four(_r2):
    assert cache_enabled() is True


@pytest.mark.anyio
async def test_cache_image_returns_none_when_disabled(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "r2_account_id", "")
    async with httpx.AsyncClient() as c:
        assert await cache_image("https://x/y.jpg", client=c) is None


# --------------------------------------------------------------------------
# Template accessor. The fallback is the safety story: a miss must degrade to
# the merchant hotlink, never to a blank tile.


class _P:
    def __init__(self, cached=None, original=None):
        self.image_cached_url = cached
        self.image_url = original


def test_product_image_prefers_the_cached_copy():
    assert product_image(_P("https://img.pk/a.jpg", "https://merchant/b.jpg")) == "https://img.pk/a.jpg"


def test_product_image_falls_back_to_the_merchant_url():
    assert product_image(_P(None, "https://merchant/b.jpg")) == "https://merchant/b.jpg"


def test_product_image_none_when_neither_exists():
    assert product_image(_P(None, None)) is None


def test_bounds_are_sane():
    assert MIN_BYTES < MAX_BYTES
    assert MAX_BYTES <= 16 * 1024 * 1024
