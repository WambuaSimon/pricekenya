"""Run one merchant's scraper end-to-end: fetch → match → upsert listing → record price history."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

from sqlmodel import Session, select

from db.models import Listing, Merchant, PriceHistory
from db.session import engine, init_db
from matching.match import match_or_create_product
from scrapers.common.base import RawListing


async def _consume(stream: AsyncIterator[RawListing], merchant_meta: dict) -> None:
    """Ingest a scraper's async stream of RawListings.

    The scraper module owns its merchant metadata (slug, name, base_url) so the
    first live run against a fresh DB can upsert the merchant row without any
    seed step. This is what makes the prod deploy work: nothing needs to be
    manually loaded into Neon before the cron scrape fires.
    """
    init_db()
    with Session(engine) as session:
        slug = merchant_meta["slug"]
        merchant = session.exec(select(Merchant).where(Merchant.slug == slug)).first()
        if not merchant:
            merchant = Merchant(**merchant_meta)
            session.add(merchant)
            session.flush()

        async for raw in stream:
            product = match_or_create_product(
                session, title=raw.title, image_url=raw.image_url
            )
            if not product:
                continue  # title we couldn't parse; v1: queue for LLM review

            # Promote a listing image to the product when the product has none.
            # Fixes the case where a merchant that doesn't ship images (Kilimall)
            # created the product first, then a merchant with images (Jumia)
            # matched to it later — without this, the product card stays blank.
            if raw.image_url and not product.image_url:
                product.image_url = raw.image_url
                session.add(product)

            listing = session.exec(
                select(Listing).where(
                    Listing.product_id == product.id,
                    Listing.merchant_id == merchant.id,
                )
            ).first()

            now = datetime.utcnow()
            price = Decimal(raw.price_kes)

            if listing:
                price_changed = listing.price_kes != price
                listing.price_kes = price
                listing.url = raw.url
                listing.title_on_merchant = raw.title
                listing.in_stock = raw.in_stock
                listing.last_checked_at = now
                session.add(listing)
                if price_changed:
                    session.add(
                        PriceHistory(
                            listing_id=listing.id,
                            price_kes=price,
                            in_stock=raw.in_stock,
                            observed_at=now,
                        )
                    )
            else:
                listing = Listing(
                    product_id=product.id,
                    merchant_id=merchant.id,
                    merchant_sku=raw.merchant_sku,
                    url=raw.url,
                    title_on_merchant=raw.title,
                    price_kes=price,
                    in_stock=raw.in_stock,
                    last_checked_at=now,
                )
                session.add(listing)
                session.flush()
                session.add(
                    PriceHistory(
                        listing_id=listing.id,
                        price_kes=price,
                        in_stock=raw.in_stock,
                        observed_at=now,
                    )
                )

        session.commit()


def run_jumia_phones() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_phones

    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_kilimall_phones() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_phones

    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


TARGETS = {
    "jumia-phones": run_jumia_phones,
    "kilimall-phones": run_kilimall_phones,
    "all-phones": lambda: (run_jumia_phones(), run_kilimall_phones()),
}


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "jumia-phones"
    fn = TARGETS.get(target)
    if not fn:
        raise SystemExit(f"Unknown scrape target: {target}. Options: {', '.join(TARGETS)}")
    fn()
