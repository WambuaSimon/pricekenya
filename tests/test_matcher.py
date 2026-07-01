"""Regression tests for the v0 deterministic matcher.

The matcher is the moat. Any change that causes these to fail must come with
either an updated expectation here AND a CONTEXT.md note, or it's a regression.
"""

import pytest

from matching.normalize import parse_title


@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Tecno Spark 30C — three spellings all merge.
        ("Tecno Spark 30C 5G 8GB+256GB Black", "tecno|spark-30c|256|8"),
        ("Tecno Spark 30 C (8+256) 5G - Magic Skin Black", "tecno|spark-30c|256|8"),
        ("Tecno Spark 30C 5G 8/256GB", "tecno|spark-30c|256|8"),
        # Infinix Hot 50 Pro+ — "Pro+" and "Pro Plus" merge.
        ("Infinix Hot 50 Pro+ 8GB 256GB", "infinix|hot-50-pro|256|8"),
        ("Infinix Hot 50 Pro Plus 256GB+8GB", "infinix|hot-50-pro|256|8"),
        # Samsung A55 — "Galaxy" noise + word-order RAM/storage all merge.
        ("Samsung Galaxy A55 5G 8GB 256GB", "samsung|a55|256|8"),
        ("Samsung A55 5G - 8/256GB - Awesome Navy", "samsung|a55|256|8"),
        ("Samsung Galaxy A55 5G 256GB 8GB RAM", "samsung|a55|256|8"),
        # Redmi → Xiaomi alias: both forms share the canonical key.
        ("Xiaomi Redmi Note 13 Pro 8+256GB", "xiaomi|note-13-pro|256|8"),
        ("Redmi Note 13 Pro 256GB 8GB", "xiaomi|note-13-pro|256|8"),
        # iPhone → Apple alias: model retains "iphone" prefix.
        ("Apple iPhone 15 128GB Blue", "apple|iphone-15|128"),
        ("iPhone 15 - 128GB - Black", "apple|iphone-15|128"),
    ],
)
def test_known_titles_produce_expected_canonical_key(title: str, expected_key: str) -> None:
    parsed = parse_title(title)
    assert parsed.canonical_key == expected_key


def test_decimal_plus_number_is_not_treated_as_storage_pair() -> None:
    """Regression: 'Battery 2.0+12 MONTHS WARRANTY' used to yield storage=12, ram=0
    because the pair regex matched '0+12'. Real specs elsewhere in the title
    ('128GB ROM +4GB RAM') should win via the gb-anchored fallback."""
    title = "Realme C100i, 128GB ROM +4GB RAM, 6.8 inches, 7000 mAh Battery, Wet Hand Touch 2.0+12 MONTHS WARRANTY"
    parsed = parse_title(title)
    assert parsed.storage_gb == 128
    assert parsed.ram_gb == 4
    assert parsed.canonical_key == "realme|c100i|128|4"


def test_full_seed_set_collapses_to_five_products() -> None:
    """The 12 seed listings must collapse to exactly 5 canonical products."""
    titles = [
        "Tecno Spark 30C 5G 8GB+256GB Black",
        "Tecno Spark 30 C (8+256) 5G - Magic Skin Black",
        "Tecno Spark 30C 5G 8/256GB",
        "Infinix Hot 50 Pro+ 8GB 256GB",
        "Infinix Hot 50 Pro Plus 256GB+8GB",
        "Samsung Galaxy A55 5G 8GB 256GB",
        "Samsung A55 5G - 8/256GB - Awesome Navy",
        "Samsung Galaxy A55 5G 256GB 8GB RAM",
        "Xiaomi Redmi Note 13 Pro 8+256GB",
        "Redmi Note 13 Pro 256GB 8GB",
        "Apple iPhone 15 128GB Blue",
        "iPhone 15 - 128GB - Black",
    ]
    keys = {parse_title(t).canonical_key for t in titles}
    assert None not in keys, "Every seed title must be parseable"
    assert len(keys) == 5
