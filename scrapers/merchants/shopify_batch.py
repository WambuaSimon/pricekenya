"""Shopify-batch fetcher — drives `/products.json` scraping across every
merchant listed in `scrapers.config.shopify_merchants`.

Same shape as `wc_batch.py`: one config-driven runner per merchant, no
per-merchant module. Add a Shopify store by appending to
SHOPIFY_MERCHANTS.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from scrapers.common.base import RawListing
from scrapers.common.shopify import fetch_shopify_catalog
from scrapers.config.shopify_merchants import SHOPIFY_MERCHANTS


async def fetch_all(merchant_slug: str) -> AsyncIterator[RawListing]:
    cfg = SHOPIFY_MERCHANTS[merchant_slug]
    meta = cfg["meta"]
    async for r in fetch_shopify_catalog(
        site_base_url=meta["base_url"],
        merchant_slug=meta["slug"],
    ):
        yield r
