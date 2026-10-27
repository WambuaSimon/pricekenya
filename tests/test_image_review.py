"""The human gate on sourced images.

An image taken from outside our merchant catalog must never reach a shopper
without someone approving it. That is not belt-and-braces, it is the only
check that works: a lookup for a title like "Oppo N6A" — which our own parser
may have invented — returns a case, a render or a different variant, and
nothing automated distinguishes that from a correct hit. A 403 errors; a
wrong image doesn't. It sits next to a price looking authoritative.

So these tests assert the gate holds, not that the resolver is clever.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from db.models import Product, ProductImageCandidate
from scrapers.common.image_sources import _og_image, search_term


@pytest.fixture()
def product(session) -> Product:
    p = Product(
        slug="oppo-n6a", canonical_key="oppo|n6a", brand="oppo",
        model="n6a", title="Oppo N6A", category_slug="phones",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def _candidate(product: Product, **kw) -> ProductImageCandidate:
    return ProductImageCandidate(
        product_id=product.id,
        image_url=kw.get("image_url", "https://www.oppo.com/x.jpg"),
        source_url=kw.get("source_url", "https://www.oppo.com/en/search/?keyword=N6A"),
        source=kw.get("source", "oppo"),
        matched_title=kw.get("matched_title", product.title),
    )


def test_a_proposal_does_not_touch_the_product(session, product):
    """The whole point. Writing a candidate must leave the product alone."""
    session.add(_candidate(product))
    session.commit()

    session.refresh(product)
    assert product.image_url is None, "a proposal published itself"


def test_candidate_defaults_to_pending(session, product):
    session.add(_candidate(product))
    session.commit()
    cand = session.exec(select(ProductImageCandidate)).one()
    assert cand.status == "pending"
    assert cand.reviewed_at is None


def test_one_open_proposal_per_product_and_source(session, product):
    """Re-running the proposer tops the queue up; it must not stack dupes."""
    session.add(_candidate(product))
    session.commit()
    session.add(_candidate(product))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_a_second_source_may_also_propose(session, product):
    """The constraint is per (product, source), not per product — two brands
    disagreeing is information for the reviewer, not a conflict."""
    session.add(_candidate(product, source="oppo"))
    session.commit()
    session.add(_candidate(product, source="gsm"))
    session.commit()
    assert len(session.exec(select(ProductImageCandidate)).all()) == 2


# --------------------------------------------------------------------------
# Resolver helpers


@pytest.mark.parametrize(
    "brand,title,expected",
    [
        ("samsung", "Samsung A17 128GB", "A17"),
        ("xiaomi", "Xiaomi Pad 7 8/256GB", "Pad 7"),
        ("nokia", "Nokia 105", "105"),
        # Our storage annotation is not part of any manufacturer's model name
        # and tanks their search box.
        ("oneplus", "Oneplus 15B 12/512GB", "15B"),
        ("honor", "Honor 600 Lite 8/256GB", "600 Lite"),
    ],
)
def test_search_term_strips_brand_and_our_own_annotations(brand, title, expected):
    assert search_term(brand, title) == expected


def test_og_image_resolves_protocol_relative_and_rooted_urls():
    base = "https://www.oppo.com/en/search/?keyword=N6A"
    assert _og_image('<meta property="og:image" content="//cdn.x/a.jpg">', base) == "https://cdn.x/a.jpg"
    assert _og_image('<meta property="og:image" content="/img/b.jpg">', base) == "https://www.oppo.com/img/b.jpg"


def test_og_image_returns_none_when_absent():
    assert _og_image("<html><head></head></html>", "https://x/") is None


@pytest.mark.anyio
async def test_unknown_brand_proposes_nothing():
    """A brand with no manufacturer resolver yields no candidate, rather than
    falling back to a generic web search. 'No result' is the useful answer."""
    import httpx

    from scrapers.common.image_sources import propose

    async with httpx.AsyncClient() as c:
        assert await propose("nonesuchbrand", "Nonesuch 9000", client=c) is None
