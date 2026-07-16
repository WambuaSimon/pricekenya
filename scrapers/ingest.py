"""Run one merchant's scraper end-to-end: fetch → match → upsert listing → record price history."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from db.models import Listing, Merchant, PriceHistory
from db.session import engine, init_db
from matching.match import match_or_create_product
from scrapers.common.base import RawListing

# Post-run sanity check thresholds. See _assert_yield_healthy for context.
MIN_PRIOR_LISTINGS_FOR_CHECK = 20
MAX_ACCEPTABLE_DROP_RATIO = 0.5


class ScraperYieldTooLow(RuntimeError):
    """Raised when a scrape produced far fewer rows than the merchant's
    prior listing count. Fails the matrix leg loudly so the Telegram
    alert fires instead of a green CI + silently-stale DB.
    """


def _assert_yield_healthy(
    *, merchant_slug: str, prior_count: int, yielded_count: int
) -> None:
    """Check post-scrape row count against the merchant's known catalog size.

    Real failure mode we've seen: a merchant rebuilds their site, the
    HTML selectors we relied on stop matching anything, and the scraper
    silently yields zero RawListings. Ingest commits nothing. Matrix leg
    exits 0. CI is green. The merchant just quietly rots in the DB — no
    Telegram alert, no signal, until someone notices on /admin/scrapes.

    Guard: after each scrape, compare yielded_count vs the merchant's
    prior listing count. If the drop is more than MAX_ACCEPTABLE_DROP_RATIO
    (default 50%) AND the merchant had >= MIN_PRIOR_LISTINGS_FOR_CHECK
    (default 20) on record, raise so exit code is non-zero.

    Skipped for merchants below the min-prior floor — new merchants have
    prior_count=0 by definition and shouldn't false-alarm every time
    they're added.
    """
    if prior_count < MIN_PRIOR_LISTINGS_FOR_CHECK:
        return
    threshold = int(prior_count * (1 - MAX_ACCEPTABLE_DROP_RATIO))
    if yielded_count < threshold:
        raise ScraperYieldTooLow(
            f"{merchant_slug}: yielded only {yielded_count} listings but "
            f"had {prior_count} on record (expected >= {threshold}). "
            f"Likely site rebuild or bot posture change — investigate "
            f"the scraper's selectors."
        )


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

        # Snapshot the merchant's existing listing count before any writes.
        # We compare this to `yielded_count` at the end to catch silent-zero
        # scrapes (see _assert_yield_healthy).
        prior_count = session.exec(
            select(func.count(Listing.id)).where(Listing.merchant_id == merchant.id)
        ).one() or 0
        yielded_count = 0

        async for raw in stream:
            yielded_count += 1
            product = match_or_create_product(
                session,
                title=raw.title,
                image_url=raw.image_url,
                category=raw.category_slug,
                description=raw.description,
            )
            if not product:
                continue  # title we couldn't parse; v1: queue for LLM review

            # Promote a listing image to the product when the product has none.
            # Fixes the case where a merchant that doesn't ship images (Kilimall)
            # created the product first, then a merchant with images (Jumia)
            # matched to it later — without this, the product card stays blank.
            # Defensive: reject known lazy-load placeholders (Avechi's
            # prod_loading.gif etc.) — otherwise the shopper sees an animated
            # loading GIF that never resolves.
            from scrapers.common.woocommerce import is_placeholder_image

            if (
                raw.image_url
                and not product.image_url
                and not is_placeholder_image(raw.image_url)
            ):
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

    # Sanity check runs OUTSIDE the session block so the writes are already
    # committed — even a legit-but-shrunk catalog should keep the fresh
    # rows in place while still alerting the operator that something's off.
    _assert_yield_healthy(
        merchant_slug=merchant_meta["slug"],
        prior_count=prior_count,
        yielded_count=yielded_count,
    )


def run_jumia_phones() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_phones

    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_kilimall_phones() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_phones

    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_jumia_tablets() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_tablets

    asyncio.run(_consume(fetch_tablets(), MERCHANT_META))


def run_kilimall_tablets() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_tablets

    asyncio.run(_consume(fetch_tablets(), MERCHANT_META))


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


def run_jumia_blenders() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_blenders

    asyncio.run(_consume(fetch_blenders(), MERCHANT_META))


def run_kilimall_blenders() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_blenders

    asyncio.run(_consume(fetch_blenders(), MERCHANT_META))


def run_jumia_toasters() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_toasters

    asyncio.run(_consume(fetch_toasters(), MERCHANT_META))


def run_kilimall_toasters() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_toasters

    asyncio.run(_consume(fetch_toasters(), MERCHANT_META))


def run_jumia_kettles() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_kettles

    asyncio.run(_consume(fetch_kettles(), MERCHANT_META))


def run_kilimall_kettles() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_kettles

    asyncio.run(_consume(fetch_kettles(), MERCHANT_META))


def run_jumia_irons() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_irons

    asyncio.run(_consume(fetch_irons(), MERCHANT_META))


def run_jumia_inverters() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_inverters

    asyncio.run(_consume(fetch_inverters(), MERCHANT_META))


def run_jumia_solar_panels() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_solar_panels

    asyncio.run(_consume(fetch_solar_panels(), MERCHANT_META))


def run_jumia_solar_batteries() -> None:
    from scrapers.merchants.jumia import MERCHANT_META, fetch_solar_batteries

    asyncio.run(_consume(fetch_solar_batteries(), MERCHANT_META))


def run_kilimall_irons() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_irons

    asyncio.run(_consume(fetch_irons(), MERCHANT_META))


def run_kilimall_inverters() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_inverters

    asyncio.run(_consume(fetch_inverters(), MERCHANT_META))


def run_kilimall_solar_panels() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_solar_panels

    asyncio.run(_consume(fetch_solar_panels(), MERCHANT_META))


def run_kilimall_solar_batteries() -> None:
    from scrapers.merchants.kilimall import MERCHANT_META, fetch_solar_batteries

    asyncio.run(_consume(fetch_solar_batteries(), MERCHANT_META))


# Hotpoint — one fetch per leaf, all through the same merchant module.
def run_hotpoint_tvs() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_tvs
    asyncio.run(_consume(fetch_tvs(), MERCHANT_META))


def run_hotpoint_refrigerators() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_refrigerators
    asyncio.run(_consume(fetch_refrigerators(), MERCHANT_META))


def run_hotpoint_washers() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_washers_dryers
    asyncio.run(_consume(fetch_washers_dryers(), MERCHANT_META))


def run_hotpoint_cooking() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_cooking
    asyncio.run(_consume(fetch_cooking(), MERCHANT_META))


def run_hotpoint_audio() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_audio
    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_hotpoint_blenders() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_blenders
    asyncio.run(_consume(fetch_blenders(), MERCHANT_META))


def run_hotpoint_toasters() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_toasters
    asyncio.run(_consume(fetch_toasters(), MERCHANT_META))


def run_hotpoint_kettles() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_kettles
    asyncio.run(_consume(fetch_kettles(), MERCHANT_META))


def run_hotpoint_irons() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_irons
    asyncio.run(_consume(fetch_irons(), MERCHANT_META))


def run_hotpoint_inverters() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_inverters
    asyncio.run(_consume(fetch_inverters(), MERCHANT_META))


def run_hotpoint_solar_panels() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_solar_panels
    asyncio.run(_consume(fetch_solar_panels(), MERCHANT_META))


def run_hotpoint_solar_batteries() -> None:
    from scrapers.merchants.hotpoint import MERCHANT_META, fetch_solar_batteries
    asyncio.run(_consume(fetch_solar_batteries(), MERCHANT_META))


def _run_hotpoint_all() -> None:
    run_hotpoint_tvs()
    run_hotpoint_refrigerators()
    run_hotpoint_washers()
    run_hotpoint_cooking()
    run_hotpoint_audio()
    run_hotpoint_blenders()
    run_hotpoint_toasters()
    run_hotpoint_kettles()
    run_hotpoint_irons()
    # Solar categories excluded until Hotpoint restocks the vertical — their
    # /solar-*/ URLs return 200 but the listings are empty as of 2026-07-07.


# Avechi (WooCommerce)
def run_avechi_phones() -> None:
    from scrapers.merchants.avechi import MERCHANT_META, fetch_phones
    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_avechi_laptops() -> None:
    from scrapers.merchants.avechi import MERCHANT_META, fetch_laptops
    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def run_avechi_tvs() -> None:
    from scrapers.merchants.avechi import MERCHANT_META, fetch_tvs
    asyncio.run(_consume(fetch_tvs(), MERCHANT_META))


def run_avechi_audio() -> None:
    from scrapers.merchants.avechi import MERCHANT_META, fetch_audio
    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_avechi_refrigerators() -> None:
    from scrapers.merchants.avechi import MERCHANT_META, fetch_refrigerators
    asyncio.run(_consume(fetch_refrigerators(), MERCHANT_META))


def run_avechi_cameras() -> None:
    from scrapers.merchants.avechi import MERCHANT_META, fetch_cameras
    asyncio.run(_consume(fetch_cameras(), MERCHANT_META))


def _run_avechi_all() -> None:
    run_avechi_phones()
    run_avechi_laptops()
    run_avechi_tvs()
    run_avechi_audio()
    run_avechi_refrigerators()
    run_avechi_cameras()


# iStore Kenya (Apple official reseller, WooCommerce)
def run_istore_phones() -> None:
    from scrapers.merchants.istore import MERCHANT_META, fetch_phones
    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_istore_laptops() -> None:
    from scrapers.merchants.istore import MERCHANT_META, fetch_laptops
    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def _run_istore_all() -> None:
    run_istore_phones()
    run_istore_laptops()


# Gadget World (Computing-focused, WooCommerce)
def run_gadgetworld_laptops() -> None:
    from scrapers.merchants.gadget_world import MERCHANT_META, fetch_laptops
    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def _run_gadgetworld_all() -> None:
    run_gadgetworld_laptops()


# Ramtons (Magento)
def run_ramtons_refrigerators() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_refrigerators
    asyncio.run(_consume(fetch_refrigerators(), MERCHANT_META))


def run_ramtons_washers() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_washers_dryers
    asyncio.run(_consume(fetch_washers_dryers(), MERCHANT_META))


def run_ramtons_cooking() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_cooking
    asyncio.run(_consume(fetch_cooking(), MERCHANT_META))


def run_ramtons_blenders() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_blenders
    asyncio.run(_consume(fetch_blenders(), MERCHANT_META))


def run_ramtons_toasters() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_toasters
    asyncio.run(_consume(fetch_toasters(), MERCHANT_META))


def run_ramtons_kettles() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_kettles
    asyncio.run(_consume(fetch_kettles(), MERCHANT_META))


def run_ramtons_irons() -> None:
    from scrapers.merchants.ramtons import MERCHANT_META, fetch_irons
    asyncio.run(_consume(fetch_irons(), MERCHANT_META))


def _run_ramtons_all() -> None:
    run_ramtons_refrigerators()
    run_ramtons_washers()
    run_ramtons_cooking()
    run_ramtons_blenders()
    run_ramtons_toasters()
    run_ramtons_kettles()
    run_ramtons_irons()


# Masoko (Safaricom's electronics shop — Next.js + Magento)
def run_masoko_phones() -> None:
    from scrapers.merchants.masoko import MERCHANT_META, fetch_phones
    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_masoko_tablets() -> None:
    from scrapers.merchants.masoko import MERCHANT_META, fetch_tablets
    asyncio.run(_consume(fetch_tablets(), MERCHANT_META))


def run_masoko_laptops() -> None:
    from scrapers.merchants.masoko import MERCHANT_META, fetch_laptops
    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def run_masoko_tvs() -> None:
    from scrapers.merchants.masoko import MERCHANT_META, fetch_tvs
    asyncio.run(_consume(fetch_tvs(), MERCHANT_META))


def run_masoko_audio() -> None:
    from scrapers.merchants.masoko import MERCHANT_META, fetch_audio
    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def _run_masoko_all() -> None:
    run_masoko_phones()
    run_masoko_tablets()
    run_masoko_laptops()
    run_masoko_tvs()
    run_masoko_audio()


# Naivas (Cloudflare-shielded, uses CffiPoliteClient)
def run_naivas_tvs() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_tvs
    asyncio.run(_consume(fetch_tvs(), MERCHANT_META))


def run_naivas_refrigerators() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_refrigerators
    asyncio.run(_consume(fetch_refrigerators(), MERCHANT_META))


def run_naivas_freezers() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_freezers
    asyncio.run(_consume(fetch_freezers(), MERCHANT_META))


def run_naivas_cooking() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_cooking
    asyncio.run(_consume(fetch_cooking(), MERCHANT_META))


def run_naivas_blenders() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_blenders
    asyncio.run(_consume(fetch_blenders(), MERCHANT_META))


def run_naivas_kettles() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_kettles
    asyncio.run(_consume(fetch_kettles(), MERCHANT_META))


def run_naivas_toasters() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_toasters
    asyncio.run(_consume(fetch_toasters(), MERCHANT_META))


def run_naivas_irons() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_irons
    asyncio.run(_consume(fetch_irons(), MERCHANT_META))


def run_naivas_audio() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_audio
    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_naivas_water_dispensers() -> None:
    from scrapers.merchants.naivas import MERCHANT_META, fetch_water_dispensers
    asyncio.run(_consume(fetch_water_dispensers(), MERCHANT_META))


def _run_naivas_all() -> None:
    run_naivas_tvs()
    run_naivas_refrigerators()
    run_naivas_freezers()
    run_naivas_cooking()
    run_naivas_blenders()
    run_naivas_kettles()
    run_naivas_toasters()
    run_naivas_irons()
    run_naivas_audio()
    run_naivas_water_dispensers()


# Phone Place Kenya (Cloudflare-shielded, uses CffiPoliteClient)
def run_phoneplace_phones() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_phones
    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_phoneplace_laptops() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_laptops
    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def run_phoneplace_audio() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_audio
    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_phoneplace_cameras() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_cameras
    asyncio.run(_consume(fetch_cameras(), MERCHANT_META))


def run_phoneplace_accessories() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_accessories
    asyncio.run(_consume(fetch_accessories(), MERCHANT_META))


def run_phoneplace_console_accessories() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_console_accessories
    asyncio.run(_consume(fetch_console_accessories(), MERCHANT_META))


def run_phoneplace_gaming() -> None:
    from scrapers.merchants.phone_place import MERCHANT_META, fetch_gaming
    asyncio.run(_consume(fetch_gaming(), MERCHANT_META))


def _run_phoneplace_all() -> None:
    run_phoneplace_phones()
    run_phoneplace_laptops()
    run_phoneplace_audio()
    run_phoneplace_cameras()
    run_phoneplace_accessories()
    run_phoneplace_console_accessories()
    run_phoneplace_gaming()


# Phones Store Kenya (phonesstorekenya.com)
def run_phonesstore_phones() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_phones
    asyncio.run(_consume(fetch_phones(), MERCHANT_META))


def run_phonesstore_tablets() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_tablets
    asyncio.run(_consume(fetch_tablets(), MERCHANT_META))


def run_phonesstore_laptops() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_laptops
    asyncio.run(_consume(fetch_laptops(), MERCHANT_META))


def run_phonesstore_audio() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_audio
    asyncio.run(_consume(fetch_audio(), MERCHANT_META))


def run_phonesstore_cameras() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_cameras
    asyncio.run(_consume(fetch_cameras(), MERCHANT_META))


def run_phonesstore_accessories() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_accessories
    asyncio.run(_consume(fetch_accessories(), MERCHANT_META))


def run_phonesstore_console_accessories() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_console_accessories
    asyncio.run(_consume(fetch_console_accessories(), MERCHANT_META))


def run_phonesstore_gaming() -> None:
    from scrapers.merchants.phones_store import MERCHANT_META, fetch_gaming
    asyncio.run(_consume(fetch_gaming(), MERCHANT_META))


def _run_phonesstore_all() -> None:
    run_phonesstore_phones()
    run_phonesstore_tablets()
    run_phonesstore_laptops()
    run_phonesstore_audio()
    run_phonesstore_cameras()
    run_phonesstore_accessories()
    run_phonesstore_console_accessories()
    run_phonesstore_gaming()


# QuickMart (session-gated, single /electronics feed → matcher routes by prodcat_id + title)
def run_quickmart_electronics() -> None:
    from scrapers.merchants.quickmart import MERCHANT_META, fetch_electronics
    asyncio.run(_consume(fetch_electronics(), MERCHANT_META))


def _run_quickmart_all() -> None:
    run_quickmart_electronics()


# Carrefour KE (MAF Next.js storefront, RSC payload parsed for structured products)
def run_carrefour_electronics() -> None:
    from scrapers.merchants.carrefour import MERCHANT_META, fetch_electronics
    asyncio.run(_consume(fetch_electronics(), MERCHANT_META))


def _run_carrefour_all() -> None:
    run_carrefour_electronics()


# Xiaomi Kenya (customised WooCommerce, single /shop/ feed → matcher routes by product_cat class)
def run_xiaomi_all() -> None:
    from scrapers.merchants.xiaomi import MERCHANT_META, fetch_all
    asyncio.run(_consume(fetch_all(), MERCHANT_META))


def _run_xiaomi_all() -> None:
    run_xiaomi_all()


# MyBigOrder (Kenyan multi-vendor marketplace, one URL per subcategory + two
# mixed appliance buckets routed by title)
def run_mybigorder_all() -> None:
    from scrapers.merchants.mybigorder import MERCHANT_META, fetch_all
    asyncio.run(_consume(fetch_all(), MERCHANT_META))


def _run_mybigorder_all() -> None:
    run_mybigorder_all()


# WC Store API merchants — use shared scrapers/common/wc_store_api.py.
# Replace the older wc-batch HTML-scraping targets which yielded 0 rows
# on these merchants because their themes hide prices from category cards.
def run_finetech() -> None:
    from scrapers.merchants.finetech import MERCHANT_META, fetch_all
    asyncio.run(_consume(fetch_all(), MERCHANT_META))


def run_techstore() -> None:
    from scrapers.merchants.techstore import MERCHANT_META, fetch_all
    asyncio.run(_consume(fetch_all(), MERCHANT_META))


def run_newmatic() -> None:
    from scrapers.merchants.newmatic import MERCHANT_META, fetch_all
    asyncio.run(_consume(fetch_all(), MERCHANT_META))


def run_patabay() -> None:
    from scrapers.merchants.patabay import MERCHANT_META, fetch_all
    asyncio.run(_consume(fetch_all(), MERCHANT_META))


def _run_all() -> None:
    run_jumia_phones()
    run_kilimall_phones()
    run_jumia_tablets()
    run_kilimall_tablets()
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
    run_jumia_blenders()
    run_kilimall_blenders()
    run_jumia_toasters()
    run_kilimall_toasters()
    run_jumia_kettles()
    run_kilimall_kettles()
    run_jumia_irons()
    run_kilimall_irons()
    run_jumia_inverters()
    run_kilimall_inverters()
    run_jumia_solar_panels()
    run_kilimall_solar_panels()
    run_jumia_solar_batteries()
    run_kilimall_solar_batteries()
    _run_hotpoint_all()
    _run_avechi_all()
    _run_istore_all()
    _run_gadgetworld_all()
    _run_ramtons_all()
    _run_masoko_all()
    _run_naivas_all()
    _run_phoneplace_all()
    _run_phonesstore_all()
    _run_quickmart_all()
    _run_carrefour_all()
    _run_xiaomi_all()
    _run_mybigorder_all()


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
    "jumia-blenders": run_jumia_blenders,
    "kilimall-blenders": run_kilimall_blenders,
    "jumia-toasters": run_jumia_toasters,
    "kilimall-toasters": run_kilimall_toasters,
    "jumia-kettles": run_jumia_kettles,
    "kilimall-kettles": run_kilimall_kettles,
    "jumia-irons": run_jumia_irons,
    "kilimall-irons": run_kilimall_irons,
    "all-phones": lambda: (run_jumia_phones(), run_kilimall_phones()),
    "jumia-tablets": run_jumia_tablets,
    "kilimall-tablets": run_kilimall_tablets,
    "all-tablets": lambda: (run_jumia_tablets(), run_kilimall_tablets()),
    "all-laptops": lambda: (run_jumia_laptops(), run_kilimall_laptops()),
    "all-tvs": lambda: (run_jumia_tvs(), run_kilimall_tvs()),
    "all-refrigerators": lambda: (run_jumia_refrigerators(), run_kilimall_refrigerators()),
    "all-washers": lambda: (run_jumia_washers(), run_kilimall_washers()),
    "all-cooking": lambda: (run_jumia_cooking(), run_kilimall_cooking()),
    "all-audio": lambda: (run_jumia_audio(), run_kilimall_audio()),
    "all-cameras": lambda: (run_jumia_cameras(), run_kilimall_cameras()),
    "all-blenders": lambda: (run_jumia_blenders(), run_kilimall_blenders()),
    "all-toasters": lambda: (run_jumia_toasters(), run_kilimall_toasters()),
    "all-kettles": lambda: (run_jumia_kettles(), run_kilimall_kettles()),
    "all-irons": lambda: (run_jumia_irons(), run_kilimall_irons()),
    "jumia-inverters": run_jumia_inverters,
    "kilimall-inverters": run_kilimall_inverters,
    "jumia-solar-panels": run_jumia_solar_panels,
    "kilimall-solar-panels": run_kilimall_solar_panels,
    "jumia-solar-batteries": run_jumia_solar_batteries,
    "kilimall-solar-batteries": run_kilimall_solar_batteries,
    # Hotpoint solar categories return empty as of 2026-07-07 — Jumia +
    # Kilimall only for now. Add hotpoint back once they restock (their
    # fetch_inverters/solar_panels/solar_batteries fns are still wired).
    "all-inverters": lambda: (
        run_jumia_inverters(),
        run_kilimall_inverters(),
    ),
    "all-solar-panels": lambda: (
        run_jumia_solar_panels(),
        run_kilimall_solar_panels(),
    ),
    "all-solar-batteries": lambda: (
        run_jumia_solar_batteries(),
        run_kilimall_solar_batteries(),
    ),
    "hotpoint-tvs": run_hotpoint_tvs,
    "hotpoint-refrigerators": run_hotpoint_refrigerators,
    "hotpoint-washers": run_hotpoint_washers,
    "hotpoint-cooking": run_hotpoint_cooking,
    "hotpoint-audio": run_hotpoint_audio,
    "hotpoint-blenders": run_hotpoint_blenders,
    "hotpoint-toasters": run_hotpoint_toasters,
    "hotpoint-kettles": run_hotpoint_kettles,
    "hotpoint-irons": run_hotpoint_irons,
    "hotpoint-inverters": run_hotpoint_inverters,
    "hotpoint-solar-panels": run_hotpoint_solar_panels,
    "hotpoint-solar-batteries": run_hotpoint_solar_batteries,
    "all-hotpoint": _run_hotpoint_all,
    "avechi-phones": run_avechi_phones,
    "avechi-laptops": run_avechi_laptops,
    "avechi-tvs": run_avechi_tvs,
    "avechi-audio": run_avechi_audio,
    "avechi-refrigerators": run_avechi_refrigerators,
    "avechi-cameras": run_avechi_cameras,
    "all-avechi": _run_avechi_all,
    "istore-phones": run_istore_phones,
    "istore-laptops": run_istore_laptops,
    "all-istore": _run_istore_all,
    "gadgetworld-laptops": run_gadgetworld_laptops,
    "all-gadgetworld": _run_gadgetworld_all,
    "ramtons-refrigerators": run_ramtons_refrigerators,
    "ramtons-washers": run_ramtons_washers,
    "ramtons-cooking": run_ramtons_cooking,
    "ramtons-blenders": run_ramtons_blenders,
    "ramtons-toasters": run_ramtons_toasters,
    "ramtons-kettles": run_ramtons_kettles,
    "ramtons-irons": run_ramtons_irons,
    "all-ramtons": _run_ramtons_all,
    "masoko-phones": run_masoko_phones,
    "masoko-tablets": run_masoko_tablets,
    "masoko-laptops": run_masoko_laptops,
    "masoko-tvs": run_masoko_tvs,
    "masoko-audio": run_masoko_audio,
    "all-masoko": _run_masoko_all,
    "naivas-tvs": run_naivas_tvs,
    "naivas-refrigerators": run_naivas_refrigerators,
    "naivas-freezers": run_naivas_freezers,
    "naivas-cooking": run_naivas_cooking,
    "naivas-blenders": run_naivas_blenders,
    "naivas-kettles": run_naivas_kettles,
    "naivas-toasters": run_naivas_toasters,
    "naivas-irons": run_naivas_irons,
    "naivas-audio": run_naivas_audio,
    "naivas-water-dispensers": run_naivas_water_dispensers,
    "all-naivas": _run_naivas_all,
    "phoneplace-phones": run_phoneplace_phones,
    "phoneplace-laptops": run_phoneplace_laptops,
    "phoneplace-audio": run_phoneplace_audio,
    "phoneplace-cameras": run_phoneplace_cameras,
    "phoneplace-accessories": run_phoneplace_accessories,
    "phoneplace-console-accessories": run_phoneplace_console_accessories,
    "phoneplace-gaming": run_phoneplace_gaming,
    "all-phoneplace": _run_phoneplace_all,
    "phonesstore-phones": run_phonesstore_phones,
    "phonesstore-tablets": run_phonesstore_tablets,
    "phonesstore-laptops": run_phonesstore_laptops,
    "phonesstore-audio": run_phonesstore_audio,
    "phonesstore-cameras": run_phonesstore_cameras,
    "phonesstore-accessories": run_phonesstore_accessories,
    "phonesstore-console-accessories": run_phonesstore_console_accessories,
    "phonesstore-gaming": run_phonesstore_gaming,
    "all-phonesstore": _run_phonesstore_all,
    "quickmart-electronics": run_quickmart_electronics,
    "all-quickmart": _run_quickmart_all,
    "carrefour-electronics": run_carrefour_electronics,
    "all-carrefour": _run_carrefour_all,
    "xiaomi-all": run_xiaomi_all,
    "all-xiaomi": _run_xiaomi_all,
    "mybigorder-all": run_mybigorder_all,
    "all-mybigorder": _run_mybigorder_all,
    # WC Store API merchants (see run_finetech etc. above)
    "finetech-ke": run_finetech,
    "techstore-ke": run_techstore,
    "newmatic-ke": run_newmatic,
    "patabay-ke": run_patabay,
    "all": _run_all,
}


# WooCommerce batch — one runner per config-driven merchant. See
# scrapers/config/wc_merchants.py for the merchant list; adding a merchant
# is a config-only change. Job names are `wc-<merchant-slug>` and `all-wc`.
def run_wc_merchant(merchant_slug: str) -> None:
    from scrapers.config.wc_merchants import WC_MERCHANTS
    from scrapers.merchants.wc_batch import fetch_all_leaves

    cfg = WC_MERCHANTS[merchant_slug]
    asyncio.run(_consume(fetch_all_leaves(merchant_slug), cfg["meta"]))


def _run_all_wc() -> None:
    from scrapers.config.wc_merchants import WC_MERCHANTS

    for slug in WC_MERCHANTS:
        run_wc_merchant(slug)


# Register `wc-<merchant>` targets programmatically from the config so we
# don't hand-maintain 14 entries. `slug=slug` in the lambda freezes the loop
# variable per iteration (classic closure trap otherwise).
from scrapers.config.wc_merchants import WC_MERCHANTS as _WC_MERCHANTS  # noqa: E402

for _slug in _WC_MERCHANTS:
    TARGETS[f"wc-{_slug}"] = (lambda slug=_slug: run_wc_merchant(slug))
TARGETS["all-wc"] = _run_all_wc


# Shopify batch — same pattern, driven by scrapers/config/shopify_merchants.py.
def run_shopify_merchant(merchant_slug: str) -> None:
    from scrapers.config.shopify_merchants import SHOPIFY_MERCHANTS
    from scrapers.merchants.shopify_batch import fetch_all

    cfg = SHOPIFY_MERCHANTS[merchant_slug]
    asyncio.run(_consume(fetch_all(merchant_slug), cfg["meta"]))


def _run_all_shopify() -> None:
    from scrapers.config.shopify_merchants import SHOPIFY_MERCHANTS

    for slug in SHOPIFY_MERCHANTS:
        run_shopify_merchant(slug)


from scrapers.config.shopify_merchants import SHOPIFY_MERCHANTS as _SHOPIFY_MERCHANTS  # noqa: E402

for _slug in _SHOPIFY_MERCHANTS:
    TARGETS[f"shopify-{_slug}"] = (lambda slug=_slug: run_shopify_merchant(slug))
TARGETS["all-shopify"] = _run_all_shopify


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "jumia-phones"
    fn = TARGETS.get(target)
    if not fn:
        raise SystemExit(f"Unknown scrape target: {target}. Options: {', '.join(TARGETS)}")
    fn()
