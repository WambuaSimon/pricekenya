"""WooCommerce-batch fetcher — one entrypoint per config-driven merchant.

Most Kenyan mid-tier electronics stores run a stock WooCommerce theme. Rather
than write one merchant module per store (~50 LOC × N merchants), we drive
everything off `scrapers.config.wc_merchants.WC_MERCHANTS`. Adding a merchant
= adding a config entry; the batch discovery script generates that entry
automatically from the merchant's homepage nav.

For merchants behind Cloudflare TLS fingerprinting (403 on plain httpx), the
config entry can set `client_type: "cffi"` and the caller switches to
`CffiPoliteClient`. Not wired in this pass — deferred until the shielded
merchants earn priority.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.woocommerce import fetch_woocommerce_category
from scrapers.config.wc_merchants import WC_MERCHANTS


async def fetch_all_leaves(merchant_slug: str) -> AsyncIterator[RawListing]:
    """Iterate every discovered category URL for one merchant and yield the
    RawListing rows. Dedupes on product URL across sibling categories — a
    product listed under both `smartphones` and `smartphones/mobile-phones`
    should not double-insert."""
    cfg = WC_MERCHANTS[merchant_slug]
    meta = cfg["meta"]
    slug = meta["slug"]
    base = meta["base_url"]
    seen: set[str] = set()
    for leaf, urls in cfg["leaf_to_urls"].items():
        for url in urls:
            async for r in fetch_woocommerce_category(
                url,
                max_pages=3,
                merchant_slug=slug,
                category_slug=leaf,
                site_base_url=base,
            ):
                if r.url in seen:
                    continue
                seen.add(r.url)
                yield r
