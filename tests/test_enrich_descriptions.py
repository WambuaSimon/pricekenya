"""Coverage for scripts/enrich_descriptions.py — the AI-agent that fills
Product.description on products the scraper couldn't get one from.

The tests use monkeypatch on the module's `_get_client` +
`_generate_description` so no real Gemini calls are made. Focus is on
selection logic, dry-run behavior, and the write path.
"""

from __future__ import annotations

from decimal import Decimal  # noqa: F401 — kept for potential future extensions

import pytest

from db.models import Product


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Skip the 5-second inter-call sleep so tests run in milliseconds."""
    from scripts import enrich_descriptions

    monkeypatch.setattr(enrich_descriptions, "_SECONDS_BETWEEN_CALLS", 0)


@pytest.fixture
def _use_test_engine(session, monkeypatch):
    """Point scripts.enrich_descriptions at the isolated test engine."""
    import db.session
    from scripts import enrich_descriptions

    monkeypatch.setattr(db.session, "engine", session.get_bind())
    monkeypatch.setattr(enrich_descriptions, "engine", session.get_bind())
    return session


def _seed_three(session):
    """Two products need enrichment, one already has a description."""
    session.add(Product(
        slug="already-has-desc",
        canonical_key="a|1",
        brand="tecno",
        model="spark 30c",
        title="Tecno Spark 30C",
        category_slug="phones",
        description="Existing description that should not be overwritten.",
    ))
    session.add(Product(
        slug="needs-desc-phone",
        canonical_key="a|2",
        brand="samsung",
        model="galaxy a55",
        title="Samsung Galaxy A55 5G 8GB 256GB",
        category_slug="phones",
        description=None,
    ))
    session.add(Product(
        slug="needs-desc-solar",
        canonical_key="a|3",
        brand="solarmax",
        model="hybrid 3kw",
        title="Solarmax Hybrid Inverter 3kW",
        category_slug="inverters",
        description="",
    ))
    session.commit()


def test_select_products_skips_already_filled(_use_test_engine):
    from scripts.enrich_descriptions import _select_products

    _seed_three(_use_test_engine)
    got = _select_products(_use_test_engine, category=None, limit=10)
    slugs = {p.slug for p in got}
    assert slugs == {"needs-desc-phone", "needs-desc-solar"}


def test_select_products_category_filter(_use_test_engine):
    from scripts.enrich_descriptions import _select_products

    _seed_three(_use_test_engine)
    got = _select_products(_use_test_engine, category="inverters", limit=10)
    assert [p.slug for p in got] == ["needs-desc-solar"]


def test_run_writes_generated_descriptions(_use_test_engine, monkeypatch):
    from sqlmodel import select

    from scripts import enrich_descriptions

    _seed_three(_use_test_engine)

    # Stub the two Gemini touchpoints so no HTTP goes out.
    monkeypatch.setattr(
        enrich_descriptions, "_get_client", lambda: object()
    )
    monkeypatch.setattr(
        enrich_descriptions,
        "_generate_description",
        lambda client, product: f"stub description for {product.slug}",
    )

    rc = enrich_descriptions.run(category=None, limit=10, dry_run=False)
    assert rc == 0

    # Check the DB reflects the writes.
    from sqlmodel import Session

    with Session(_use_test_engine.get_bind()) as s:
        phone = s.exec(select(Product).where(Product.slug == "needs-desc-phone")).one()
        solar = s.exec(select(Product).where(Product.slug == "needs-desc-solar")).one()
        already = s.exec(select(Product).where(Product.slug == "already-has-desc")).one()
        assert phone.description == "stub description for needs-desc-phone"
        assert solar.description == "stub description for needs-desc-solar"
        assert already.description == "Existing description that should not be overwritten."


def test_dry_run_makes_no_writes(_use_test_engine, monkeypatch, capsys):
    from sqlmodel import Session, select

    from scripts import enrich_descriptions

    _seed_three(_use_test_engine)
    monkeypatch.setattr(enrich_descriptions, "_get_client", lambda: object())
    monkeypatch.setattr(
        enrich_descriptions,
        "_generate_description",
        lambda client, product: f"DRY {product.slug}",
    )

    rc = enrich_descriptions.run(category=None, limit=10, dry_run=True)
    assert rc == 0

    captured = capsys.readouterr()
    assert "DRY needs-desc-phone" in captured.out
    assert "DRY needs-desc-solar" in captured.out

    with Session(_use_test_engine.get_bind()) as s:
        phone = s.exec(select(Product).where(Product.slug == "needs-desc-phone")).one()
        assert phone.description is None  # NOT overwritten in dry-run


def test_run_bails_when_client_unavailable(_use_test_engine, monkeypatch):
    from scripts import enrich_descriptions

    _seed_three(_use_test_engine)
    monkeypatch.setattr(enrich_descriptions, "_get_client", lambda: None)

    rc = enrich_descriptions.run(category=None, limit=10, dry_run=False)
    assert rc == 1


def test_no_products_to_enrich_exits_clean(_use_test_engine, monkeypatch, capsys):
    from scripts import enrich_descriptions

    # No seed → nothing to enrich.
    monkeypatch.setattr(enrich_descriptions, "_get_client", lambda: object())
    monkeypatch.setattr(
        enrich_descriptions,
        "_generate_description",
        lambda client, product: "unreachable",
    )

    rc = enrich_descriptions.run(category=None, limit=10, dry_run=False)
    assert rc == 0
    assert "no products need enrichment" in capsys.readouterr().out
