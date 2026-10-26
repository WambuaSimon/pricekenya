"""Images we refuse to store, and the one we let overwrite them.

`Product.image_url` is hotlinked straight from the merchant by the shopper's
browser, so a merchant that 403s those requests costs us the image while the
scrape itself still reports success. Seven hosts do this wholesale
(scrapers/common/image_hosts.py).

The damage was not the 403 itself — the card has a brand-name fallback tile
behind every image — it was that the old promotion rule fired only when
`product.image_url` was NULL. First writer won permanently. Because a phone
carried by many merchants is likelier to have been seen early by one of the
blocking hosts, the breakage concentrated precisely on the products the
default `shops` sort puts at the top of /c/phones: measured 2026-10-26, 84%+
of phones with 6+ merchants showed a blank tile against 5.7% of
single-merchant ones.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlmodel import select

from db.models import Listing, Merchant, Product
from scrapers.common.base import RawListing
from scrapers.common.image_hosts import is_blocked_image_host
from scrapers.ingest import _upsert_one_listing

GOOD_IMAGE = "https://ke.jumia.is/unsafe/fit-in/300x300/product/25/0873723/1.jpg"
BLOCKED_IMAGE = "https://www.phoneplacekenya.com/wp-content/uploads/2026/05/x.webp"


@pytest.fixture()
def merchants(session) -> dict[str, int]:
    out = {}
    for slug, name, base in [
        ("phone-place", "Phone Place Kenya", "https://www.phoneplacekenya.com"),
        ("jumia-ke", "Jumia Kenya", "https://www.jumia.co.ke"),
    ]:
        m = Merchant(slug=slug, name=name, base_url=base)
        session.add(m)
        session.commit()
        session.refresh(m)
        out[slug] = m.id
    return out


def _raw(merchant_slug: str, image_url: str | None, url: str) -> RawListing:
    # One title so both merchants match to the same Product — that collision
    # is the whole point of the promotion rule under test.
    return RawListing(
        merchant_slug=merchant_slug,
        merchant_sku=None,
        category_slug="phones",
        title="Apple iPhone 14 Pro Max 256GB",
        url=url,
        price_kes=Decimal("76000"),
        in_stock=True,
        image_url=image_url,
    )


def _product(session) -> Product:
    products = session.exec(select(Product)).all()
    assert len(products) == 1, f"expected one matched product, got {len(products)}"
    return products[0]


@pytest.mark.parametrize(
    "url,expected",
    [
        (BLOCKED_IMAGE, True),
        ("https://phoneplacekenya.com/x.jpg", True),       # bare apex
        ("https://WWW.PricePoint.co.ke:443/x.webp", True),  # case + port
        (GOOD_IMAGE, False),
        ("https://avechi.co.ke/wp-content/uploads/x.jpg", False),
        ("https://notphoneplacekenya.com/x.jpg", False),    # suffix, not host
        (None, False),
        ("", False),
        ("not a url", False),
    ],
)
def test_is_blocked_image_host(url, expected):
    assert is_blocked_image_host(url) is expected


def test_blocked_image_is_not_stored(session, merchants):
    """A known-dead URL is worse than NULL: NULL is repairable."""
    _upsert_one_listing(
        session,
        _raw("phone-place", BLOCKED_IMAGE, "https://www.phoneplacekenya.com/p/1"),
        merchants["phone-place"],
    )

    assert _product(session).image_url is None


def test_working_image_replaces_a_blocked_one(session, merchants):
    """The regression this file exists for.

    Under the old `not product.image_url` guard the Jumia URL was discarded
    and the product kept the 403 forever.
    """
    _upsert_one_listing(
        session,
        _raw("phone-place", BLOCKED_IMAGE, "https://www.phoneplacekenya.com/p/1"),
        merchants["phone-place"],
    )
    _upsert_one_listing(
        session,
        _raw("jumia-ke", GOOD_IMAGE, "https://www.jumia.co.ke/p-1.html"),
        merchants["jumia-ke"],
    )

    assert _product(session).image_url == GOOD_IMAGE


def test_blocked_image_does_not_overwrite_a_working_one(session, merchants):
    """The upgrade is one-way. Scrape order must not undo a good image."""
    _upsert_one_listing(
        session,
        _raw("jumia-ke", GOOD_IMAGE, "https://www.jumia.co.ke/p-1.html"),
        merchants["jumia-ke"],
    )
    _upsert_one_listing(
        session,
        _raw("phone-place", BLOCKED_IMAGE, "https://www.phoneplacekenya.com/p/1"),
        merchants["phone-place"],
    )

    assert _product(session).image_url == GOOD_IMAGE


def test_working_image_does_not_overwrite_a_working_one(session, merchants):
    """Unchanged behaviour: first usable writer still wins among good hosts.

    Guards against the new branch widening into a general last-writer-wins,
    which would make a product's image flap with scrape order.
    """
    other = "https://img.kilimall.com/gallery/store/1/x.png"
    _upsert_one_listing(
        session,
        _raw("jumia-ke", GOOD_IMAGE, "https://www.jumia.co.ke/p-1.html"),
        merchants["jumia-ke"],
    )
    _upsert_one_listing(
        session,
        _raw("phone-place", other, "https://www.phoneplacekenya.com/p/1"),
        merchants["phone-place"],
    )

    assert _product(session).image_url == GOOD_IMAGE


# --------------------------------------------------------------------------
# The repair pass, scripts/fetch_missing_images.py --repair-broken.
#
# The ingest fix above only heals a product when some non-blocked merchant
# re-scrapes it AND that scraper returns a card image. Plenty don't (Kilimall
# lazy-loads its thumbnails, so its cards carry no src at all), which is why
# the repair pass goes to the merchant's detail page for og:image instead.
# Network is stubbed here; what's under test is which listings it will and
# won't ask about.

import asyncio  # noqa: E402

from scripts import fetch_missing_images as fmi  # noqa: E402


def test_repair_skips_blocked_listings_and_images(monkeypatch):
    """Never fetch a blocked merchant, never accept a blocked og:image."""
    asked: list[str] = []

    async def fake_try(url: str):
        asked.append(url)
        # The non-blocked merchant answers with a URL on a blocked CDN —
        # a replacement exactly as dead as what it would replace.
        if "kilimall" in url:
            return BLOCKED_IMAGE
        return GOOD_IMAGE

    monkeypatch.setattr(fmi, "_try_one_listing", fake_try)

    listings = [
        Listing(
            product_id=1,
            merchant_id=1,
            url="https://www.phoneplacekenya.com/p/1",
            title_on_merchant="x",
            price_kes=Decimal("1"),
        ),
        Listing(
            product_id=1,
            merchant_id=2,
            url="https://www.kilimall.co.ke/p/2",
            title_on_merchant="x",
            price_kes=Decimal("1"),
        ),
        Listing(
            product_id=1,
            merchant_id=3,
            url="https://www.jumia.co.ke/p-3.html",
            title_on_merchant="x",
            price_kes=Decimal("1"),
        ),
    ]
    found = asyncio.run(fmi._fetch_for_product(Product(), listings))

    assert found == GOOD_IMAGE
    assert "https://www.phoneplacekenya.com/p/1" not in asked, (
        "blocked merchant was fetched anyway"
    )
    assert asked == [
        "https://www.kilimall.co.ke/p/2",
        "https://www.jumia.co.ke/p-3.html",
    ]


def test_repair_mode_targets_blocked_as_well_as_missing(session, monkeypatch):
    """--repair-broken widens the target set; the default mode must not."""
    session.add_all(
        [
            Product(
                slug="a", canonical_key="a", brand="Apple", model="x", title="A",
                image_url=BLOCKED_IMAGE, category_slug="phones",
            ),
            Product(
                slug="b", canonical_key="b", brand="Apple", model="y", title="B",
                image_url=None, category_slug="phones",
            ),
            Product(
                slug="c", canonical_key="c", brand="Apple", model="z", title="C",
                image_url=GOOD_IMAGE, category_slug="phones",
            ),
        ]
    )
    session.commit()

    # Each product needs at least one listing: _run skips listing-less rows
    # before it ever reaches the fetch, so without these the assertion would
    # pass for the wrong reason.
    for product in session.exec(select(Product)).all():
        session.add(
            Listing(
                product_id=product.id,
                merchant_id=1,
                url=f"https://www.jumia.co.ke/{product.slug}.html",
                title_on_merchant=product.title,
                price_kes=Decimal("1"),
            )
        )
    session.commit()

    seen: list[str] = []

    async def fake_fetch(product, listings):
        seen.append(product.slug)
        return None

    monkeypatch.setattr(fmi, "_fetch_for_product", fake_fetch)

    asyncio.run(fmi._run(session, None, None, True, True))
    assert sorted(seen) == ["a", "b"], "repair mode missed the blocked-host row"

    seen.clear()
    asyncio.run(fmi._run(session, None, None, True, False))
    assert seen == ["b"], "default mode must stay NULL-only"
