"""Regression tests for the TV matcher.

The TV category has a very different spec profile from phones/laptops — model
SKUs are inconsistent, screen size drives most decisions, and Kenyan brands
(Vitron, Amtec, Cube, Vision Plus) are as common as global ones. These tests
lock in the essential merge behavior and the non-TV rejections.
"""

import pytest

from matching.normalize import parse_title


@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Common Kenyan brands
        ("Cube CBT43S 43 Inch Smart TV - Black", "cube|43|smart"),
        ("Amtec 32R1S, 32\" Inch Frameless Android LED Smart TV", "amtec|32|led|smart"),
        ("Vitron HTC3288QS, 32 inch QLED Smart Android TV", "vitron|32|qled|smart"),
        # Compound brand
        ("Vision Plus VP8843SW 43\" Frameless FHD Smart TV", "vision-plus|43|fhd|smart"),
        # Global brands
        ("Samsung 55 Inch UHD 4K Smart TV Series 7 55AU7000", "samsung|55|4k|smart"),
        ("LG 43 Inch Full HD Smart TV WebOS", "lg|43|fhd|smart"),
        ("Sony 65 Inch 4K Ultra HD Android Smart Bravia TV KD-65X75", "sony|65|4k|smart"),
        ("Hisense 32 Inch HD LED Smart TV Vidaa OS", "hisense|32|led|smart"),
        # Non-smart TV
        ("Globalstar 32UK50, 32INCH DIGITAL AC/DC TV Frameless", "globalstar|32|basic"),
        ("Solarmax 22 Inches 22F01 Digital TV Full HD", "solarmax|22|fhd|basic"),
    ],
)
def test_real_tv_titles_parse_to_expected_key(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="tvs")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Hisense Soundbar 140 Watts 2.1 Channel, HS1800",
        "Android 14.0 8K TV Box 4GB RAM 64GB ROM Dual Band WiFi Smart Media Player",
        "Universal Wall Mount for 32-55 Inch TVs",
        "TV Remote Control Universal Replacement",
        "HDMI Cable 2 Meters 4K",
    ],
)
def test_non_tv_items_are_rejected(title: str) -> None:
    """Soundbars, TV boxes, wall mounts and other TV-adjacent items must be
    dropped so the TV catalog stays honest."""
    parsed = parse_title(title, category="tvs")
    assert parsed.canonical_key is None


def test_hd_alone_is_not_a_canonical_differentiator() -> None:
    """"HD" appears as marketing filler in many Kenyan TV titles ("QLED HD Netflix"),
    so titles that differ only by whether "HD" is mentioned should still merge —
    but titles that explicitly claim FHD or 4K should split as they should."""
    a = parse_title("Vitron 32 inch QLED Smart TV", category="tvs").canonical_key
    b = parse_title("Vitron 32 inch QLED Smart TV HD Netflix", category="tvs").canonical_key
    assert a == b == "vitron|32|qled|smart"

    fhd = parse_title("Vitron 32 inch QLED Full HD Smart TV", category="tvs").canonical_key
    assert fhd == "vitron|32|fhd|qled|smart"
    assert fhd != a


def test_smart_and_basic_split_correctly() -> None:
    smart = parse_title("Samsung 43 inch 4K Smart TV", category="tvs").canonical_key
    basic = parse_title("Samsung 43 inch 4K TV", category="tvs").canonical_key
    assert smart == "samsung|43|4k|smart"
    assert basic == "samsung|43|4k|basic"


def test_condition_captured() -> None:
    p = parse_title("Refurbished Samsung 55 inch 4K Smart TV", category="tvs")
    assert p.specs.get("condition") == "refurbished"
    assert "refurbished" in p.canonical_key
