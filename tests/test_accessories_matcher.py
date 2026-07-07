"""Regression tests for the accessories matcher.

One module handles chargers / power banks / cables / smartwatches / styluses /
earbuds / controllers / peripherals across three leaf categories, dispatched
via the normalize.py category map. Tests cover:
  - the happy path per type in the correct leaf
  - the accepted-type gate that keeps a gaming controller out of the
    phone-tablet-accessories feed (and vice versa)
  - the "no distinguishing spec" drop that keeps two unrelated silicone
    cases from false-merging across merchants
"""

import pytest

from matching.normalize import parse_title

# ---------------------------------------------------------------------------
# Power banks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Oraimo Traveler 20W 20000mAh Power Bank", "oraimo|power-bank|20000mah"),
        ("Anker 10000mAh PowerCore Power Bank", "anker|power-bank|10000mah"),
        ("Baseus 20000mAh 65W Power Bank Fast Charge", "baseus|power-bank|20000mah"),
    ],
)
def test_power_bank_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


def test_power_bank_without_capacity_dropped() -> None:
    # Without mAh we can't safely merge across merchants.
    p = parse_title("Anker Portable Power Bank", category="phone-tablet-accessories")
    assert p.canonical_key is None


# ---------------------------------------------------------------------------
# Chargers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Apple 20W USB-C Power Adapter", "apple|charger|20w"),
        ("Anker 65W GaN Fast Charger USB-C", "anker|charger|65w"),
        ("Baseus 30W Wall Charger", "baseus|charger|30w"),
        ("Samsung 25W Super Fast Charging Adapter", "samsung|charger|25w"),
    ],
)
def test_charger_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Apple MagSafe Charger 15W", "apple|wireless-charger|15w"),
        ("Baseus 20W Qi Wireless Charger Pad", "baseus|wireless-charger|20w"),
    ],
)
def test_wireless_charger_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


def test_car_charger_title() -> None:
    p = parse_title(
        "Anker 40W Car Charger Dual USB-C", category="phone-tablet-accessories"
    )
    assert p.canonical_key == "anker|car-charger|40w"


# ---------------------------------------------------------------------------
# Cables
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Apple USB-C to Lightning Cable 1m", "apple|cable|usbc-lightning"),
        ("Anker USB-C to USB-C Cable 2m", "anker|cable|usbc-usbc"),
        ("Baseus Lightning Cable 1.5m", "baseus|cable|usba-lightning"),
    ],
)
def test_cable_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


def test_cable_without_connectors_dropped() -> None:
    # "Anker Cable" alone is unmergeable — no connector info at all.
    p = parse_title("Anker Charging Cable Braided", category="phone-tablet-accessories")
    assert p.canonical_key is None


# ---------------------------------------------------------------------------
# Smartwatches
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Apple Watch Series 10 GPS 42mm", "apple|smartwatch|series-10"),
        ("Apple Watch SE 40mm", "apple|smartwatch|se"),
        ("Apple Watch Ultra 2 49mm Titanium", "apple|smartwatch|ultra-2"),
        ("Samsung Galaxy Watch 7 44mm Wi-Fi", "samsung|smartwatch|7"),
        ("Samsung Galaxy Watch Ultra Titanium", "samsung|smartwatch|ultra"),
    ],
)
def test_smartwatch_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Apple Pencil / stylus
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Apple Pencil Pro", "apple|stylus|pro"),
        ("Apple Pencil (USB-C)", "apple|stylus|usb-c"),
        ("Apple Pencil (2nd Generation)", "apple|stylus|2gen"),
    ],
)
def test_apple_pencil_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Earbuds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Apple AirPods Pro 2 with USB-C", "apple|earbuds|airpods-pro-2"),
        ("Apple AirPods 4", "apple|earbuds|airpods-4"),
        ("Apple AirPods Max Blue", "apple|earbuds|airpods-max"),
    ],
)
def test_earbud_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="phone-tablet-accessories").canonical_key == expected_key


# ---------------------------------------------------------------------------
# Peripherals leaf — mouse / keyboard / hub
# ---------------------------------------------------------------------------

def test_gaming_mouse_in_peripherals() -> None:
    p = parse_title(
        "Logitech G502 Gaming Mouse", category="peripherals-accessories"
    )
    assert p.canonical_key == "logitech|mouse|g502"


def test_mechanical_keyboard_in_peripherals() -> None:
    p = parse_title(
        "Redragon K552 Mechanical Keyboard Rainbow",
        category="peripherals-accessories",
    )
    assert p.canonical_key == "redragon|keyboard|k552"


# ---------------------------------------------------------------------------
# Console leaf — controllers / gaming headsets
# ---------------------------------------------------------------------------

def test_ps5_controller_in_console() -> None:
    p = parse_title(
        "Sony DualSense Wireless Controller PS5 CFI-ZCT1W",
        category="console-accessories",
    )
    assert p.canonical_key and p.canonical_key.startswith("sony|controller|")


def test_gaming_headset_in_console() -> None:
    p = parse_title(
        "HyperX Cloud II Gaming Headset KHX-HSCP-RD",
        category="console-accessories",
    )
    assert p.canonical_key and p.canonical_key.startswith("hyperx|")


# ---------------------------------------------------------------------------
# Cross-leaf rejections — the accepted-type gate is what keeps a gaming
# controller out of phone-tablet-accessories etc.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "category,title",
    [
        # Controller in the phones leaf → rejected
        ("phone-tablet-accessories",
         "Sony DualSense Wireless Controller PS5 CFI-ZCT1W"),
        # Wall charger in the console leaf → rejected
        ("console-accessories", "Apple 20W USB-C Power Adapter"),
        # Case in peripherals → rejected
        ("peripherals-accessories", "Spigen iPhone 15 Case Silicone Black"),
    ],
)
def test_wrong_leaf_rejected(category: str, title: str) -> None:
    parsed = parse_title(title, category=category)
    assert parsed.canonical_key is None


# ---------------------------------------------------------------------------
# Brand + generic-noise rejections
# ---------------------------------------------------------------------------

def test_no_brand_rejected() -> None:
    # Generic 20W charger with no recognisable brand — nothing to merge on.
    p = parse_title(
        "Fast Charging 20W Wall Adapter", category="phone-tablet-accessories"
    )
    assert p.canonical_key is None


def test_accessory_of_accessory_rejected() -> None:
    # Case FOR AirPods isn't a phone accessory in the sense we want to index.
    p = parse_title(
        "Silicone Case for AirPods Pro Black",
        category="phone-tablet-accessories",
    )
    assert p.canonical_key is None


def test_phone_stand_rejected() -> None:
    # Passive stands / holders don't participate in price comparison usefully.
    p = parse_title(
        "Baseus Adjustable Phone Stand Aluminum",
        category="phone-tablet-accessories",
    )
    assert p.canonical_key is None
