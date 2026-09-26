"""<lastmod> must mean "the offers changed", not "we looked at them".

It used to be max(Listing.last_checked_at), which every scrape bumps on
every listing it sees whether or not anything moved. Measured on prod
2026-09-25 that put 75% of the sitemap (4,255 of 5,668 products) on one
lastmod date: each cron run told Google ~4,300 pages had changed when
~1,100 had.

Google is explicit that it starts ignoring lastmod once it proves
unreliable, and an ignored lastmod means Google recrawls on its own
schedule rather than ours — expensive with 4,166 URLs sitting in
"Discovered - currently not indexed" waiting for crawl budget.

PriceHistory is the honest source: ingest writes a row when a listing first
appears and whenever its price or stock actually moves, and at no other
time.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlmodel import select

from db.models import Listing, Merchant, PriceHistory, Product
from scrapers.common.base import RawListing
from scrapers.ingest import _upsert_one_listing

#: Parses to canonical_key "samsung|a17" — see matching/phone.py.
TITLE = "Samsung Galaxy A17 128GB"


def _lastmod_for(session, slug: str) -> str | None:
    from app.routes.meta import _build_sitemap_xml

    out = _build_sitemap_xml(session)
    xml = out[0] if isinstance(out, tuple) else out
    m = re.search(
        rf"<url><loc>[^<]*/p/{re.escape(slug)}</loc><lastmod>([^<]+)</lastmod>", xml
    )
    if m:
        return m.group(1)
    # Tolerate attribute/whitespace drift in the serializer.
    block = re.search(rf"<loc>[^<]*/p/{re.escape(slug)}</loc>.*?</url>", xml, re.S)
    if not block:
        return None
    inner = re.search(r"<lastmod>([^<]+)</lastmod>", block.group(0))
    return inner.group(1) if inner else None


@pytest.fixture()
def seeded(session):
    """One indexable product: image, two live merchants, known history."""
    for mid in (1, 2):
        session.add(Merchant(id=mid, slug=f"m{mid}", name=f"M{mid}",
                             base_url=f"https://m{mid}.example"))
    # Title and canonical_key must be what matching/phone.py actually
    # produces, or _upsert_one_listing refuses the row (unparseable title)
    # and silently updates nothing — which is how the first draft of these
    # tests fooled itself.
    p = Product(slug="samsung-a17", canonical_key="samsung|a17", brand="samsung",
                model="a17", title="Samsung Galaxy A17", category_slug="phones",
                image_url="https://img.example/p.jpg")
    session.add(p)
    session.commit()
    session.refresh(p)

    old = datetime.utcnow() - timedelta(days=30)
    for mid in (1, 2):
        lst = Listing(product_id=p.id, merchant_id=mid,
                      url=f"https://m{mid}.example/p", title_on_merchant=TITLE,
                      price_kes=Decimal("10000"), in_stock=True,
                      last_checked_at=datetime.utcnow())  # checked NOW
        session.add(lst)
        session.commit()
        session.refresh(lst)
        session.add(PriceHistory(listing_id=lst.id, price_kes=Decimal("10000"),
                                 in_stock=True, observed_at=old))  # changed 30d AGO
    session.commit()
    return p


def test_lastmod_follows_the_price_change_not_the_check(session, seeded):
    """The core regression: checked today, last changed 30 days ago."""
    lastmod = _lastmod_for(session, seeded.slug)

    assert lastmod is not None
    expected = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
    assert lastmod.startswith(expected), (
        f"lastmod {lastmod} should reflect the 30-day-old price change, "
        "not today's check"
    )


def test_a_rescrape_that_changes_nothing_does_not_move_lastmod(session, seeded):
    """The exact scrape-cycle behaviour that made lastmod untrustworthy."""
    before = _lastmod_for(session, seeded.slug)

    raw = RawListing(
        merchant_slug="m1", merchant_sku=None, category_slug="phones",
        title=TITLE, url="https://m1.example/p",
        price_kes=Decimal("10000"), in_stock=True, image_url=None,
    )
    _upsert_one_listing(session, raw, 1)  # same price, same stock
    session.expire_all()

    assert _lastmod_for(session, seeded.slug) == before


def test_a_real_price_change_does_move_lastmod(session, seeded):
    before = _lastmod_for(session, seeded.slug)

    raw = RawListing(
        merchant_slug="m1", merchant_sku=None, category_slug="phones",
        title=TITLE, url="https://m1.example/p",
        price_kes=Decimal("8500"), in_stock=True, image_url=None,
    )
    _upsert_one_listing(session, raw, 1)
    session.expire_all()

    after = _lastmod_for(session, seeded.slug)
    assert after != before
    assert after.startswith(datetime.utcnow().date().isoformat())


def test_stock_flip_is_recorded_as_a_change(session, seeded):
    """A listing going sold-out removes a row from "Where to buy" and can
    change the cheapest price. It wrote no history row at all while ingest
    only compared price."""
    listing = session.exec(
        select(Listing).where(Listing.merchant_id == 1)
    ).one()
    before = len(session.exec(
        select(PriceHistory).where(PriceHistory.listing_id == listing.id)
    ).all())

    raw = RawListing(
        merchant_slug="m1", merchant_sku=None, category_slug="phones",
        title=TITLE, url="https://m1.example/p",
        price_kes=Decimal("10000"), in_stock=False, image_url=None,  # same price
    )
    _upsert_one_listing(session, raw, 1)
    session.expire_all()

    after = session.exec(
        select(PriceHistory).where(PriceHistory.listing_id == listing.id)
    ).all()
    assert len(after) == before + 1, "stock change must be recorded"
    assert after[-1].in_stock is False


def test_product_without_history_still_gets_a_lastmod(session, seeded):
    """Fallback path: a slightly stale lastmod beats none at all."""
    session.exec(select(PriceHistory)).all()
    for h in session.exec(select(PriceHistory)).all():
        session.delete(h)
    session.commit()

    assert _lastmod_for(session, seeded.slug) is not None
