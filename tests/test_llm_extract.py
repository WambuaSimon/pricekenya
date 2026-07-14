"""Unit tests for matching/llm_extract.py.

Gemini is mocked. We verify:
- The flag gates the whole path.
- Successful extraction produces a ParsedTitle with a valid canonical_key.
- Two consecutive calls with the same title produce ONE mocked API call
  (title-hash dedup via LlmExtractionLog).
- The per-category daily cap short-circuits without touching the SDK.
- Invalid response (LLM says not-a-phone) returns None.
- SDK errors are captured and never propagate to the caller.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from db.models import LlmExtractionLog

pytestmark = pytest.mark.usefixtures("session")


class _FakePhonePayload:
    """Mirrors what google-genai would hydrate into resp.parsed."""

    def __init__(self, data: dict):
        self._data = data

    def model_dump(self) -> dict:
        return self._data


@pytest.fixture
def enable_llm(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "llm_fallback_enabled", True)
    monkeypatch.setattr(config.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(config.settings, "llm_daily_cap_per_category", 500)
    monkeypatch.setattr(config.settings, "gemini_timeout_seconds", 5.0)
    # Reset the LRU cache between tests so hash lookups don't cross-contaminate.
    from matching import llm_extract

    llm_extract._cached_lookup_key.cache_clear()
    yield
    llm_extract._cached_lookup_key.cache_clear()


def _install_fake_gemini(monkeypatch, response_payload: dict, counter: dict):
    """Replace _call_gemini_sync so no network hits and we can count calls."""
    from matching import llm_extract

    def fake_sync(**kwargs):
        counter["calls"] = counter.get("calls", 0) + 1
        return response_payload

    monkeypatch.setattr(llm_extract, "_call_gemini_sync", fake_sync)
    # Bypass the executor timeout by making it a direct sync call.
    monkeypatch.setattr(
        llm_extract,
        "_call_with_timeout",
        lambda prompt, title, schema: fake_sync(),
    )


def test_flag_off_returns_none(session):
    from matching.llm_extract import extract

    assert extract(session, title="ambiguous title", category="phones") is None


def test_extract_writes_log_and_produces_key(session, enable_llm, monkeypatch):
    counter: dict = {}
    _install_fake_gemini(
        monkeypatch,
        {
            "is_valid_for_category": True,
            "brand": "tecno",
            "model": "spark 30c",
            "storage_gb": 256,
            "ram_gb": 8,
        },
        counter,
    )
    from matching.llm_extract import extract

    parsed = extract(
        session, title="Tecno Spark 30C mystery 5G bundle", category="phones"
    )
    session.commit()
    assert parsed is not None
    assert parsed.canonical_key == "tecno|spark-30c|256|8"
    assert counter["calls"] == 1

    logged = session.exec(select(LlmExtractionLog)).all()
    assert len(logged) == 1
    assert logged[0].parsed_ok is True
    assert logged[0].category == "phones"


def test_second_call_same_title_uses_cache(session, enable_llm, monkeypatch):
    counter: dict = {}
    _install_fake_gemini(
        monkeypatch,
        {
            "is_valid_for_category": True,
            "brand": "tecno",
            "model": "spark 30c",
            "storage_gb": 256,
            "ram_gb": 8,
        },
        counter,
    )
    from matching.llm_extract import extract

    extract(session, title="Tecno Spark 30C mystery 5G", category="phones")
    session.commit()
    extract(session, title="Tecno Spark 30C mystery 5G", category="phones")
    session.commit()
    assert counter["calls"] == 1  # second call replayed from the log


def test_daily_cap_short_circuits(session, enable_llm, monkeypatch):
    from datetime import datetime

    from app import config
    from matching.llm_extract import extract

    monkeypatch.setattr(config.settings, "llm_daily_cap_per_category", 2)
    for i in range(3):
        session.add(
            LlmExtractionLog(
                title=f"prior {i}",
                title_hash=f"h{i}",
                category="phones",
                latency_ms=10,
                parsed_ok=True,
                created_at=datetime.utcnow(),
            )
        )
    session.commit()

    counter: dict = {}
    _install_fake_gemini(
        monkeypatch,
        {"is_valid_for_category": True, "brand": "tecno", "model": "spark 30c"},
        counter,
    )
    result = extract(session, title="new title", category="phones")
    assert result is None
    assert counter.get("calls", 0) == 0


def test_invalid_category_response_returns_none(session, enable_llm, monkeypatch):
    counter: dict = {}
    _install_fake_gemini(
        monkeypatch,
        {"is_valid_for_category": False, "brand": None},
        counter,
    )
    from matching.llm_extract import extract

    result = extract(session, title="Just a random accessory", category="phones")
    session.commit()
    assert result is None
    # Log row still written so we know we spent an API call.
    logs = session.exec(select(LlmExtractionLog)).all()
    assert len(logs) == 1
    assert logs[0].parsed_ok is False


def test_sdk_exception_swallowed(session, enable_llm, monkeypatch):
    from matching import llm_extract

    def boom(**kwargs):
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr(llm_extract, "_call_with_timeout", lambda **_: boom())
    result = llm_extract.extract(session, title="anything", category="phones")
    session.commit()
    assert result is None
    logs = session.exec(select(LlmExtractionLog)).all()
    assert len(logs) == 1
    assert logs[0].parsed_ok is False
    assert logs[0].error is not None


def test_unknown_category_returns_none(session, enable_llm, monkeypatch):
    from matching.llm_extract import extract

    result = extract(session, title="doesn't matter", category="mystery-slug")
    assert result is None
