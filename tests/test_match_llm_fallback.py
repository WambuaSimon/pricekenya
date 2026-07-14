"""Integration test: match_or_create_product with the LLM fallback wired in.

Verifies:
- Flag off + unparseable title still returns None (regression guard).
- Flag on + mocked LLM creates a real Product with the composed canonical_key.
"""

from __future__ import annotations

from sqlmodel import select

from db.models import Product


def test_flag_off_still_drops(session, monkeypatch):
    from app import config
    from matching.match import match_or_create_product

    monkeypatch.setattr(config.settings, "llm_fallback_enabled", False)
    # A garbled title the phone parser rejects.
    result = match_or_create_product(
        session, title="???? mystery bundle ???", category="phones"
    )
    assert result is None
    assert session.exec(select(Product)).first() is None


def test_llm_enriches_shallow_regex_parse(session, monkeypatch):
    """When the regex parser gives a brand|type-only key (e.g. `jbl|speaker`)
    for a title like 'JBL Charge 5 Portable Speaker', the LLM must be invoked
    to try to add a model code — otherwise different JBL SKUs all collapse
    into the same bucket.
    """
    from app import config
    from matching import llm_extract
    from matching.match import match_or_create_product

    monkeypatch.setattr(config.settings, "llm_fallback_enabled", True)
    monkeypatch.setattr(config.settings, "gemini_api_key", "test-key")
    llm_extract._cached_lookup_key.cache_clear()

    # Return a payload with a proper model_code so the composed key is deeper.
    monkeypatch.setattr(
        llm_extract,
        "_call_with_timeout",
        lambda prompt, title, schema: {
            "is_valid_for_category": True,
            "brand": "jbl",
            "type": "speaker",
            "model_code": "charge 5",
            "channels": None,
            "watts": None,
            "wireless": True,
            "condition": "new",
        },
    )

    result = match_or_create_product(
        session,
        title="JBL Charge 5 Portable Bluetooth Speaker",
        category="audio",
    )
    session.commit()
    assert result is not None
    # LLM-enriched key must beat the shallow regex `jbl|speaker`.
    assert result.canonical_key == "jbl|speaker|charge-5"


def test_llm_fallback_creates_product(session, monkeypatch):
    from app import config
    from matching import llm_extract
    from matching.match import match_or_create_product

    monkeypatch.setattr(config.settings, "llm_fallback_enabled", True)
    monkeypatch.setattr(config.settings, "gemini_api_key", "test-key")
    llm_extract._cached_lookup_key.cache_clear()

    monkeypatch.setattr(
        llm_extract,
        "_call_with_timeout",
        lambda prompt, title, schema: {
            "is_valid_for_category": True,
            "brand": "tecno",
            "model": "spark 30c",
            "storage_gb": 256,
            "ram_gb": 8,
        },
    )

    # A title the regex parser can't extract from — no known brand token —
    # so the LLM branch fires.
    result = match_or_create_product(
        session, title="??? mystery smartphone bundle ???", category="phones"
    )
    session.commit()
    assert result is not None
    assert result.canonical_key == "tecno|spark-30c|256|8"
    assert result.brand == "tecno"
    products = session.exec(select(Product)).all()
    assert len(products) == 1
