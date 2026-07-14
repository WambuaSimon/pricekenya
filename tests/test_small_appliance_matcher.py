"""Regression tests for the small-appliances matcher.

One module handles blenders, toasters, kettles, and irons — each dispatched
via the normalize.py category map. Tests cover both the happy path per type
and the cross-type rejection that keeps a kettle out of the toasters feed.
"""

import pytest

from matching.normalize import parse_title

# ---------------------------------------------------------------------------
# Blenders
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Ramtons 1.5L Blender - 400W Glass Jar", "ramtons|blender|1.5l"),
        ("Mika MBL2101 - Jug Blender, 1.5L, 400W - Black", "mika|blender|jug|mbl2101|1.5l"),
        ("Ramtons Portable Personal Blender 400ML 300W", "ramtons|blender|personal"),
        ("Ailyons Immersion Hand Blender 2 Speed 300W", "ailyons|blender|immersion"),
        ("SmartPro Juicer Blender 2L 500W", "smartpro|blender|juicer|2l"),
    ],
)
def test_blender_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="blenders").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Toasters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Ramtons RM/258 - 2 Slice Toaster - White", "ramtons|toaster|2-slot"),
        ("Von 4 Slice Bread Toaster HT242 - Black 1400W", "von|toaster|4-slot"),
        ("Nunix 2 slice bread toaster", "nunix|toaster|2-slot"),
        # Toaster oven — capacity keys the SKU, not slots. Two-digit capacity
        # must parse correctly (was a regression in a single-digit-only regex).
        ("Mika 22L Toaster Oven MTO2201 - Grey", "mika|toaster|oven|22l"),
    ],
)
def test_toaster_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="toasters").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Kettles
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        (
            "Ramtons RM/263 1.7L Cordless Electric Kettle Stainless Steel",
            "ramtons|kettle|1.7l|stainless",
        ),
        ("Mika MKT2202 Glass Kettle 1.7L 1500W", "mika|kettle|1.7l|glass"),
        ("Von 1.8L Plastic Kettle Cordless - White", "von|kettle|1.8l|plastic"),
    ],
)
def test_kettle_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="kettles").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Irons
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Ramtons RM/442 Steam Iron 2400W", "ramtons|iron|steam"),
        ("Mika Dry Iron MDI1101 1000W", "mika|iron|dry"),
        ("Von HGI2410 Garment Steamer 1800W", "von|iron|garment-steamer"),
    ],
)
def test_iron_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="ironing-laundry").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Cross-type rejections — the expected-type gate is what keeps a kettle out
# of the toasters feed etc.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "category,title",
    [
        ("toasters", "Mika 1.5L Blender 400W"),                  # blender in toasters
        ("kettles", "Ramtons Bread Toaster 4-Slice"),            # toaster in kettles
        ("blenders", "Silicone Kitchen Blender Bottle Water 500ml"),  # blender bottle
        ("ironing-laundry", "Wooden Iron Board 110cm Adjustable"),   # ironing board
        ("ironing-laundry", "Hair Straightener Curling Iron 2-in-1"),  # hair styling
    ],
)
def test_wrong_category_or_accessory_rejected(category: str, title: str) -> None:
    parsed = parse_title(title, category=category)
    assert parsed.canonical_key is None


def test_no_brand_rejected() -> None:
    """A generic 1.5L Blender with no recognizable brand shouldn't index —
    we have nothing to merge on and would false-merge with every other
    generic blender."""
    p = parse_title("Portable 1.5L Blender 400W", category="blenders")
    assert p.canonical_key is None
