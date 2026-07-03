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
                session,
                title=raw.title,
                image_url=raw.image_url,
                category=raw.category_slug,
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


def run_jumia_laptops() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_laptops

    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def run_kilimall_laptops() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_laptops

    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def run_jumia_tvs() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_tvs

    asyncio.run(_consume(fetch_tvs(), MERCHANT_META))


def run_kilimall_tvs() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_tvs

    asyncio.run(_consume(fetch_tvs(), MERCHANT_META))


def run_jumia_refrigerators() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_refrigerators

    asyncio.run(_consume(fetch_refrigerators(), MERCHANT_META))


def run_kilimall_refrigerators() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_refrigerators

    asyncio.run(_consume(fetch_refrigerators(), MERCHANT_META))


def run_jumia_washers() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_washers_dryers

    asyncio.run(_consume(fetch_washers_dryers(), MERCHANT_META))


def run_kilimall_washers() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_washers_dryers

    asyncio.run(_consume(fetch_washers_dryers(), MERCHANT_META))


def run_jumia_cooking() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_cooking

    asyncio.run(_consume(fetch_cooking(), MERCHANT_META))


def run_kilimall_cooking() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_cooking

    asyncio.run(_consume(fetch_cooking(), MERCHANT_META))


def run_jumia_audio() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_audio

    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_kilimall_audio() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_audio

    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_jumia_cameras() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_cameras

    asyncio.run(_consume(fetch_cameras(), MERCHANT_META))


def run_kilimall_cameras() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_cameras

    asyncio.run(_consume(fetch_cameras(), MERCHANT_META))


def _run_all() -> None:
    run_jumia_phones()
    run_kilimall_phones()
    run_jumia_laptops()
    run_kilimall_laptops()
    run_jumia_tvs()
    run_kilimall_tvs()
    run_jumia_refrigerators()
    run_kilimall_refrigerators()
    run_jumia_washers()
    run_kilimall_washers()
    run_jumia_cooking()
    run_kilimall_cooking()
    run_jumia_audio()
    run_kilimall_audio()
    run_jumia_cameras()
    run_kilimall_cameras()


TARGETS = {
    "jumia-phones": run_jumia_phones,
    "kilimall-phones": run_kilimall_phones,
    "jumia-laptops": run_jumia_laptops,
    "kilimall-laptops": run_kilimall_laptops,
    "jumia-tvs": run_jumia_tvs,
    "kilimall-tvs": run_kilimall_tvs,
    "jumia-refrigerators": run_jumia_refrigerators,
    "kilimall-refrigerators": run_kilimall_refrigerators,
    "jumia-washers": run_jumia_washers,
    "kilimall-washers": run_kilimall_washers,
    "jumia-cooking": run_jumia_cooking,
    "kilimall-cooking": run_kilimall_cooking,
    "jumia-audio": run_jumia_audio,
    "kilimall-audio": run_kilimall_audio,
    "jumia-cameras": run_jumia_cameras,
    "kilimall-cameras": run_kilimall_cameras,
    "all-phones": lambda: (run_jumia_phones(), run_kilimall_phones()),
    "all-laptops": lambda: (run_jumia_laptops(), run_kilimall_laptops()),
    "all-tvs": lambda: (run_jumia_tvs(), run_kilimall_tvs()),
    "all-refrigerators": lambda: (run_jumia_refrigerators(), run_kilimall_refrigerators()),
    "all-washers": lambda: (run_jumia_washers(), run_kilimall_washers()),
    "all-cooking": lambda: (run_jumia_cooking(), run_kilimall_cooking()),
    "all-audio": lambda: (run_jumia_audio(), run_kilimall_audio()),
    "all-cameras": lambda: (run_jumia_cameras(), run_kilimall_cameras()),
    "all": _run_all,
}


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "jumia-phones"
    fn = TARGETS.get(target)
    if not fn:
        raise SystemExit(f"Unknown scrape target: {target}. Options: {', '.join(TARGETS)}")
    fn()
