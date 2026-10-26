"""Hosts whose product images we must not store, because they never render.

`Product.image_url` is a hotlink: the shopper's browser fetches it straight
from the merchant. A merchant that 403s those requests (or has deleted the
files) therefore costs us the image even though the scrape itself succeeded,
and nothing in the scrape path notices — the URL was present and well-formed
when we wrote it.

Measured 2026-10-26 by requesting 12 randomly-sampled live `image_url`s per
host with a browser UA and no Referer, which is exactly what the card markup
produces (`referrerpolicy="no-referrer"` in _product_grid.html):

    www.phoneplacekenya.com      12/12  403   blocks regardless of Referer
    pricepoint.co.ke             12/12  403
    techonline.co.ke             12/12  403
    eamobitech.com               12/12  403
    www.smartdeviceskenya.co.ke  12/12  404   uploads deleted
    www.budgetcomputers.co.ke    10/10  conn  host unreachable
    finetech.co.ke                5/5   conn  domain lapsed (see ingest.py)

These are *wholesale* failures — every sampled URL on the host fails, so the
host is predictive and belongs here. Hosts that rot only partially
(zurimall.co.ke 3/12, smartphoneskenya.co.ke 1/12) are deliberately absent:
a host denylist would throw away their working majority. Those are caught
per-URL by `scripts/fetch_missing_images.py --repair-broken`, which probes
the actual stored URL instead of guessing from its host.

Keep this list short and evidence-backed. Re-probe before adding a host: a
merchant that starts serving images again should come straight back off it.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Compared against the URL host case-insensitively, with any leading "www."
# removed on both sides so a scraper that emits the bare apex is still caught.
BLOCKED_IMAGE_HOSTS = frozenset(
    {
        "phoneplacekenya.com",
        "pricepoint.co.ke",
        "techonline.co.ke",
        "eamobitech.com",
        "smartdeviceskenya.co.ke",
        "budgetcomputers.co.ke",
        "finetech.co.ke",
    }
)


def _normalize_host(host: str) -> str:
    host = host.lower().partition(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_blocked_image_host(url: str | None) -> bool:
    """True when `url` points at a host that refuses to serve us images.

    Used in two places: `scrapers/ingest.py` refuses to *store* such a URL
    (and lets a working one from another merchant replace one already
    stored), and the repair script uses it to skip those merchants when
    hunting for a replacement image.
    """
    if not url:
        return False
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:  # malformed URL — not our problem to fix here
        return False
    return _normalize_host(host) in BLOCKED_IMAGE_HOSTS
