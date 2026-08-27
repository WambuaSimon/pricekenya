"""A scraped price too large to be real must never reach the database.

Regression cover for the smartdevices-ke rows that shipped KSh 86,000,000,000
for a washing machine. The merchant's own category HTML carries that figure
verbatim (86,000 x 1e6), so the scraper parsed it correctly and the ingest
layer stored it. Ten such rows were live, and because every price-spread
figure on the site derives from max(price), they corrupted the homepage gap
cards, the product page's "Dearest" panel and the category grid's
"Save up to" line.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlmodel import select

from db.models import Listing, Merchant, Product
from scrapers.common.base import RawListing
from scrapers.ingest import (
    MAX_PLAUSIBLE_PRICE_KES,
    _upsert_one_listing,
    price_is_plausible,
)


@pytest.fixture()
def merchant_id(session) -> int:
    m = Merchant(
        slug="smartdevices-ke",
        name="Smart Devices Kenya",
        base_url="https://www.smartdeviceskenya.co.ke",
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m.id


def _raw(price: str) -> RawListing:
    return RawListing(
        merchant_slug="smartdevices-ke",
        merchant_sku=None,
        category_slug="washers-dryers",
        title="Hisense 10KG Front Load Washing Machine WD3Q1043BT",
        url="https://www.smartdeviceskenya.co.ke/product/hisense-10kg/",
        price_kes=Decimal(price),
        in_stock=True,
        image_url=None,
    )


@pytest.mark.parametrize(
    "price,expected",
    [
        ("0", False),          # floor: scrapers already drop these
        ("-1", False),
        ("1", True),
        ("2499995", True),     # the priciest genuine live listing: a 116" TV
        ("20000000", True),    # boundary is inclusive
        ("20000001", False),
        ("86000000000", False),  # observed verbatim in the merchant's HTML
        ("639950072995", False),
    ],
)
def test_price_is_plausible(price, expected):
    assert price_is_plausible(Decimal(price)) is expected


def test_implausible_price_is_not_stored(session, merchant_id):
    """The listing is dropped rather than clamped or stored."""
    _upsert_one_listing(session, _raw("86000000000"), merchant_id)

    assert session.exec(select(Listing)).all() == []


def test_implausible_price_creates_no_orphan_product(session, merchant_id):
    """Rejection happens before match_or_create_product.

    That ordering matters: matching is itself a write, so validating after it
    would leave a Product row with no sellable listing behind — which the
    category grid would then render as a card with no price.
    """
    _upsert_one_listing(session, _raw("86000000000"), merchant_id)

    assert session.exec(select(Product)).all() == []


def test_plausible_price_still_stored(session, merchant_id):
    """The guard must not be so tight it rejects a real expensive product."""
    _upsert_one_listing(session, _raw("2499995"), merchant_id)

    listings = session.exec(select(Listing)).all()
    assert len(listings) == 1
    assert listings[0].price_kes == Decimal("2499995")


def test_boundary_price_is_stored(session, merchant_id):
    _upsert_one_listing(session, _raw(str(MAX_PLAUSIBLE_PRICE_KES)), merchant_id)

    assert len(session.exec(select(Listing)).all()) == 1
