"""Regression tests for the laptop matcher.

Real Kenyan retail laptop titles are messy — heavy refurb/renewed market,
brand-missing titles ("ThinkPad X270 …"), and non-laptop items leaking into
the laptop category (flash drives). These tests lock in the expected canonical
keys for common patterns.
"""

import pytest

from matching.normalize import parse_title


@pytest.mark.parametrize(
    "title,expected_key",
    [
        # HP EliteBook family — CPU gen, storage type, refurb all captured
        (
            "Elitebook 840 G3 (Refurbished), Intel Core i5 6th Gen, 8GB RAM, 256GB SSD",
            "hp|elitebook-840-g3|i5-6|8|256-ssd|refurbished",
        ),
        # Brand-inferred from ThinkPad line, gen extracted from SKU (i5-8350U = 8th gen)
        (
            "Lenovo ThinkPad X280 Intel Core I5-8350U Quad-Core 8GB RAM 256GB SSD 12.5\"",
            "lenovo|thinkpad-x280|i5-8|8|256-ssd",
        ),
        # MacBook Pro — "Pro" is a variant qualifier, not noise
        (
            "Apple MacBook Pro 13\"- Core I5 -8GB RAM, 256GB SSD (2012) Laptop",
            "apple|macbook-pro|i5|8|256-ssd",
        ),
        # Chromebook 11 — variant includes both "11" and "g7"
        (
            "Refurbished HP Chromebook 11 G7 - Intel Celeron - 4GB RAM",
            "hp|chromebook-11-g7|celeron|4|refurbished",
        ),
        # Brand missing, model line implies brand (ThinkPad → lenovo)
        (
            "ThinkPad X270 Intel Core I5-Refurbished-8GB RAM 256GB SSD Windows 10 Pro Laptop",
            "lenovo|thinkpad-x270|i5|8|256-ssd|refurbished",
        ),
        # No-space storage "256SSD" still recognized, RAM 16GB not double-counted as storage
        (
            "BRAND NEW LAPTOPS LENOVO THINKPAD X13 16GBRAM G1 256SSD 10TH GENERATION",
            "lenovo|thinkpad-x13|16|256-ssd",
        ),
        # ProBook with a slash in the model — takes the first
        (
            "ProBook 640 G4/G5-Core i5-8th Gen-8GB RAM-256GB SSD- Refurbished-14\"",
            "hp|probook-640|i5-8|8|256-ssd|refurbished",
        ),
        # Dell Latitude with Pentium CPU
        (
            "Dell Latitude 3190 INTEL PENTIUM 4GB RAM 128 GB SSD 12 Inch Screen Refurbished Laptop",
            "dell|latitude-3190|pentium|4|128-ssd|refurbished",
        ),
    ],
)
def test_real_laptop_titles_parse_to_expected_key(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="laptops")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Sandisk 64GB ultra Flair USB 3.0 Flash disk",
        "Blueing 14\" Laptop N3350 6GB+192GB SSD Portable Computer Student Pc",
        "Some cheap generic laptop bag",
    ],
)
def test_non_laptop_or_unknown_brand_yields_unparsed(title: str) -> None:
    """Flash drives and unbranded generic products should be dropped, not
    forced into the laptop index."""
    parsed = parse_title(title, category="laptops")
    assert parsed.canonical_key is None


def test_two_titles_for_same_elitebook_merge() -> None:
    """The Jumia and Kilimall listings for the same EliteBook 840 G1 refurb
    must produce the same canonical key so they merge across merchants."""
    jumia_title = "Refurbished EliteBook 840 G1 Core I5 8GB RAM 256GB SSD"
    kili_title = "HP laptops EliteBook 840 G1 8GB Ram, 256GB SSD, 14'' Screen Refurbished Intel Core I5"
    a = parse_title(jumia_title, category="laptops").canonical_key
    b = parse_title(kili_title, category="laptops").canonical_key
    assert a == b == "hp|elitebook-840-g1|i5|8|256-ssd|refurbished"


def test_condition_appears_in_specs() -> None:
    parsed = parse_title("Refurbished Lenovo ThinkPad T480 i5 8GB 256GB SSD", category="laptops")
    assert parsed.specs.get("condition") == "refurbished"


def test_new_condition_default() -> None:
    parsed = parse_title("Lenovo ThinkPad T480 i5 8GB 256GB SSD", category="laptops")
    assert parsed.specs.get("condition") == "new"


def test_820_and_840_do_not_merge() -> None:
    """Regression: EliteBook 820 and 840 previously collapsed to hp|elitebook|...
    because trailing punctuation ("820,") failed the variant match and Kilimall
    puts the model number before the line word ("HP Laptops 840 ... Elitebook")."""
    a = parse_title("Refurbished HP EliteBook 820, Intel Core I5, 8GB RAM 256GB SSD", category="laptops")
    b = parse_title(
        "HP Laptops 840 8GB RAM, 256GB SSD Elitebook Refurbished Laptop 14''",
        category="laptops",
    )
    assert a.canonical_key.startswith("hp|elitebook-820|")
    assert b.canonical_key.startswith("hp|elitebook-840|")
    assert a.canonical_key != b.canonical_key
