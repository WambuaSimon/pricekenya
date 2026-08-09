"""ProductRedirect: 301 old slugs to their merged-into successor.

Two surfaces:
- app/routes/products.py: on 404, checks ProductRedirect and 301s
- scripts/coarsen_phones_backfill.py: writes ProductRedirect rows +
  chain-collapses when a winner is itself later merged
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from db.models import Listing, Merchant, Product, ProductRedirect


@pytest.fixture
def client(session):
    from app.main import app
    from db.session import get_session

    def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def _make_product(session, *, slug: str, brand: str = "samsung", model: str = "s25"):
    p = Product(
        slug=slug,
        canonical_key=f"{brand}|{model}|{slug}",
        brand=brand,
        model=model,
        title=f"{brand.title()} {model.title()} ({slug})",
        category_slug="phones",
    )
    session.add(p)
    session.commit()
    return p


# ---------------------------------------------------------------------------
# product_detail 404 handler
# ---------------------------------------------------------------------------


def test_missing_slug_with_no_redirect_returns_404(client):
    resp = client.get("/p/never-existed")
    assert resp.status_code == 404


def test_missing_slug_with_redirect_returns_301(client, session):
    _make_product(session, slug="samsung-s25")
    session.add(ProductRedirect(old_slug="samsung-s25-128-8", new_slug="samsung-s25"))
    session.commit()

    resp = client.get("/p/samsung-s25-128-8", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"] == "/p/samsung-s25"


def test_live_product_takes_priority_over_redirect(client, session):
    """If a slug is both a live Product AND has a stale ProductRedirect row
    (e.g. slug was reused), the live product wins."""
    _make_product(session, slug="samsung-s25")
    session.add(ProductRedirect(old_slug="samsung-s25", new_slug="samsung-s26"))
    session.commit()

    resp = client.get("/p/samsung-s25")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# coarsen_phones_backfill: writes ProductRedirect + chain-collapses
# ---------------------------------------------------------------------------


def _seed_merge_scenario(session, monkeypatch):
    """Two Products with the same coarsened key (samsung|s25), one with
    2 listings (winner), one with 1. Merging should register a redirect
    from loser → winner."""
    # Point the script at the test engine.
    import db.session
    import scripts.coarsen_phones_backfill as backfill

    monkeypatch.setattr(db.session, "engine", session.get_bind())
    monkeypatch.setattr(backfill, "engine", session.get_bind())

    session.add(Merchant(id=1, slug="jumia", name="Jumia", base_url="https://x"))
    session.add(Merchant(id=2, slug="kilimall", name="Kilimall", base_url="https://y"))
    session.commit()

    winner = _make_product(session, slug="samsung-s25")
    loser = _make_product(session, slug="samsung-s25-128-8-legacy")

    for i, (pid, mid) in enumerate([(winner.id, 1), (winner.id, 2), (loser.id, 1)]):
        session.add(Listing(
            product_id=pid, merchant_id=mid,
            url=f"https://x/{i}", title_on_merchant="s25",
            price_kes=Decimal("50000"), in_stock=True,
        ))
    session.commit()
    return winner, loser


def test_backfill_writes_redirect_row(session, monkeypatch):
    winner, loser = _seed_merge_scenario(session, monkeypatch)
    # Grab slugs BEFORE the merge — loser gets deleted, so accessing
    # attributes on the stale ORM object after the merge raises
    # ObjectDeletedError.
    winner_slug = winner.slug
    loser_slug = loser.slug

    from scripts.coarsen_phones_backfill import run

    rc = run(category="phones", dry_run=False)
    assert rc == 0

    # Redirect row exists pointing loser → winner.
    redirect = session.exec(
        select(ProductRedirect).where(ProductRedirect.old_slug == loser_slug)
    ).first()
    assert redirect is not None
    assert redirect.new_slug == winner_slug

    # Loser Product is gone.
    assert session.exec(
        select(Product).where(Product.slug == loser_slug)
    ).first() is None


def test_record_redirect_collapses_chains(session):
    """If A → B is registered, then later B → C is registered, the A row
    gets rewritten to A → C in one hop."""
    from scripts.coarsen_phones_backfill import _record_redirect

    _record_redirect(session, old_slug="a", new_slug="b")
    _record_redirect(session, old_slug="b", new_slug="c")
    session.commit()

    a = session.get(ProductRedirect, "a")
    b = session.get(ProductRedirect, "b")
    assert a is not None and a.new_slug == "c"  # rewritten!
    assert b is not None and b.new_slug == "c"


def test_record_redirect_upserts_existing_mapping(session):
    """Re-running the same merge doesn't duplicate; the existing row
    gets its new_slug updated (idempotent)."""
    from scripts.coarsen_phones_backfill import _record_redirect

    _record_redirect(session, old_slug="a", new_slug="b")
    _record_redirect(session, old_slug="a", new_slug="c")
    session.commit()

    a = session.get(ProductRedirect, "a")
    assert a.new_slug == "c"
    all_rows = session.exec(select(ProductRedirect)).all()
    assert len(all_rows) == 1
