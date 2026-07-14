"""Smoke tests for matching/embeddings.py.

sentence-transformers is an optional dep; skip cleanly if unavailable so CI
without the extra doesn't fail.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sentence_transformers")


def test_encode_requires_allow(monkeypatch):
    from matching import embeddings

    monkeypatch.setattr(embeddings, "ALLOW_ENCODE", False)
    with pytest.raises(RuntimeError, match="allow_encode"):
        embeddings.encode("Tecno Spark 30C")


def test_encode_shape_and_cosine():
    from matching import embeddings

    embeddings.allow_encode()
    a = embeddings.encode("Tecno Spark 30C 8/256GB")
    b = embeddings.encode("Tecno Spark 30C 5G 8+256GB")
    c = embeddings.encode("Samsung 55\" QLED Smart TV")
    assert len(a) == embeddings.EMBED_BYTES == 1536
    self_sim = embeddings.cosine(a, a)
    near_sim = embeddings.cosine(a, b)
    far_sim = embeddings.cosine(a, c)
    assert self_sim == pytest.approx(1.0, abs=1e-4)
    assert near_sim > far_sim
    assert near_sim > 0.7   # semantic proximity for same product family
    assert far_sim < 0.5    # phone vs TV should read as unrelated


def test_obvious_diff_filter_catches_screenshot_cases():
    """The five false-positive pairs from a real user screenshot must be
    filtered out before they reach the review queue.
    """
    from matching.match import _obviously_different_products as diff

    # LG 75" 4K TV vs LG 65" 4K LED TV — screen size differs.
    assert diff(
        {"screen_inches": 75, "smart": False, "condition": "new", "resolution": "4K"},
        "lg|75|4k|basic",
        {"screen_inches": 65, "smart": False, "condition": "new", "resolution": "4K", "panel_type": "LED"},
        "lg|65|4k|basic",
    )
    # Syinix 55" 4K Smart vs Syinix 65" 4K QLED Smart.
    assert diff(
        {"screen_inches": 55}, "syinix|55|4k|smart",
        {"screen_inches": 65}, "syinix|65|4k|qled|smart",
    )
    # Realme C11 2/32 vs C100I 4/64 — model and storage/RAM differ.
    assert diff(
        {"storage_gb": 32, "ram_gb": 2}, "realme|c11|32|2",
        {"storage_gb": 64, "ram_gb": 4}, "realme|c100i|64|4",
    )
    # Logitech Keyboard MK220 vs MK270 — model code only, no numeric spec.
    assert diff(
        {"type": "Keyboard", "model": "MK220"}, "logitech|keyboard|mk220",
        {"type": "Keyboard", "model": "MK270"}, "logitech|keyboard|mk270",
    )

    # Real duplicates should NOT be filtered out — the reviewer must still see them.
    assert not diff(
        {"storage_gb": 256, "ram_gb": 12}, "samsung|flip-7|256|12",
        {"storage_gb": 256, "ram_gb": 12}, "samsung|flip7|256|12",
    )
    # Macbook M4 in one key, missing in other — length differs, no numeric
    # spec conflict on shared positions. Legit borderline for review.
    assert not diff(
        {"ram_gb": 16, "storage_gb": 512}, "apple|macbook-air|m4|16|512-ssd",
        {"ram_gb": 16, "storage_gb": 512}, "apple|macbook-air|16|512-ssd",
    )


def test_loose_key_guardrail_examples():
    """The auto-merge guardrail — regressions here would let MiniLM's blind
    spot on short titles collapse legitimately-separate SKUs.
    """
    from matching.match import _canonical_key_matches_loosely as m

    # Real duplicates the guardrail SHOULD accept.
    assert m("samsung|flip-7|256|12", "samsung|flip7|256|12")
    assert m("xiaomi|redmi-15c|128|8", "xiaomi|redmi15c|128|8")
    assert m("infinix|hot-60-pro|256|8", "infinix|hot-60pro|256|8")

    # Different products the guardrail MUST reject.
    assert not m("oppo|a5|64|4", "oppo|a5s|64|4")            # A5 vs A5S
    assert not m("oppo|r9|64|4", "oppo|r9s|64|4")            # R9 vs R9S
    assert not m("tecno|spark-40|128|8", "tecno|spark-40|256|8")   # storage diff
    assert not m("tecno|spark-40|128|8", "tecno|spark-40|128|4")   # RAM diff
    assert not m("xiaomi|redmi-15c|128|8", "xiaomi|redmi-15|128|8")  # 15C vs 15


def test_web_isolation_invariant():
    """The FastAPI web app must never load sentence_transformers.

    Guards against a routing / template / config change that accidentally
    imports embeddings from a module the web tier reaches.
    """
    import sys

    # sentence_transformers may have been imported by earlier tests here,
    # so pop it before the check.
    sys.modules.pop("sentence_transformers", None)
    sys.modules.pop("torch", None)

    from app.main import app  # noqa: F401 — importing is the whole test
    assert "sentence_transformers" not in sys.modules, (
        "app.main triggered a sentence_transformers import — the web tier "
        "must never load PyTorch. Check matching/embeddings.py imports."
    )
