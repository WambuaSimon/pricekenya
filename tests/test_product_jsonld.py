"""Product structured data must never advertise an offer it cannot price.

Search Console reported a critical "Missing field 'lowPrice' (in 'offers')".
A product with no live offers has no price, so the AggregateOffer came out as

    {"@type": "AggregateOffer", "priceCurrency": "KES", "offerCount": 0}

with no lowPrice and no highPrice. Measured on prod 2026-09-06 that was
firing on 3,874 products — 43.5% of the catalog.

Dropping only the offers key would have traded one error for another: Google
treats a Product with no offers, review or aggregateRating as incomplete too.
These pages are already noindex (app/indexing.py wants 2+ merchants), so the
fix is to emit no product markup at all for a page we are asking Google not
to index.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from db.models import Listing, Merchant, Product


def _ld(html: str) -> dict:
    """Every JSON-LD block on the page, keyed by @type. Parsing also proves
    the templated JSON is still well-formed."""
    out = {}
    for raw in re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.S
    ):
        d = json.loads(raw)
        out[d["@type"]] = d
    return out


@pytest.fixture()
def product(session) -> Product:
    session.add(Merchant(id=1, slug="m1", name="M1", base_url="https://m1.example"))
    session.add(Merchant(id=2, slug="m2", name="M2", base_url="https://m2.example"))
    p = Product(
        slug="test-phone", canonical_key="brand|test", brand="brand",
        model="test", title="Brand Test Phone", category_slug="phones",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _offer(session, product_id: int, merchant_id: int, price: str, in_stock: bool = True):
    session.add(Listing(
        product_id=product_id, merchant_id=merchant_id,
        url=f"https://m{merchant_id}.example/p", title_on_merchant="Brand Test Phone",
        price_kes=Decimal(price), in_stock=in_stock, last_checked_at=datetime.utcnow(),
    ))
    session.commit()


def test_no_product_markup_when_there_are_no_offers(session, product):
    """The regression. No price means no priceable AggregateOffer."""
    body = TestClient(app).get(f"/p/{product.slug}").text
    assert "Product" not in _ld(body)


def test_breadcrumb_still_emitted_without_offers(session, product):
    """BreadcrumbList is valid regardless and must not be collateral damage."""
    assert "BreadcrumbList" in _ld(TestClient(app).get(f"/p/{product.slug}").text)


def test_out_of_stock_only_counts_as_no_offers(session, product):
    """A dead listing is not an offer — it must not resurrect the markup."""
    _offer(session, product.id, 1, "19999", in_stock=False)
    assert "Product" not in _ld(TestClient(app).get(f"/p/{product.slug}").text)


def test_single_offer_emits_a_priced_aggregate(session, product):
    """One merchant is still noindex, but its markup is valid: low == high."""
    _offer(session, product.id, 1, "19999")
    offers = _ld(TestClient(app).get(f"/p/{product.slug}").text)["Product"]["offers"]

    assert offers["lowPrice"] == 19999.0
    assert offers["highPrice"] == 19999.0
    assert offers["offerCount"] == 1


def test_multi_offer_spans_low_to_high(session, product):
    _offer(session, product.id, 1, "19999")
    _offer(session, product.id, 2, "24500")
    offers = _ld(TestClient(app).get(f"/p/{product.slug}").text)["Product"]["offers"]

    assert offers["lowPrice"] == 19999.0
    assert offers["highPrice"] == 24500.0
    assert offers["offerCount"] == 2


def test_every_emitted_aggregate_has_a_low_price(session, product):
    """The invariant Search Console actually checks, stated directly."""
    client = TestClient(app)

    ld = _ld(client.get(f"/p/{product.slug}").text)
    assert "Product" not in ld, "no offers, so no markup to be missing a price"

    _offer(session, product.id, 1, "19999")
    ld = _ld(client.get(f"/p/{product.slug}").text)
    assert "lowPrice" in ld["Product"]["offers"]
