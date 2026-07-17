"""Regression tests for the 2026-07-17 kitchen-catalog matchers:
dishwashers, coffee-machines, and home_fixtures (sinks/countertops/etc.).

Fixtures use real Newmatic + Jumia listing titles so coverage matches
production drift when a matcher marker changes.
"""

import pytest

from matching.normalize import parse_title

# ---------------------------------------------------------------------------
# Dishwashers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        (
            "Newmatic N60 F55 Built-in Dishwasher - 15 Place Settings, 5 Programs",
            "newmatic|dishwasher|built-in|15ps",
        ),
        (
            "Bosch Serie 4 Freestanding Dishwasher 12 Place Settings",
            "bosch|dishwasher|freestanding|12ps",
        ),
        (
            "Beko Countertop Dishwasher 6 Place Settings",
            "beko|dishwasher|countertop|6ps",
        ),
    ],
)
def test_dishwasher_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="dishwashers").canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        # Not real dishwashers — Jumia "dishwasher" search noise
        "Smartraha life RahaLife 20inch Stainless Steel Dish Rack-2 Tier",
        "Sunlight Dish Washing Paste Lemon - 800g",
        "Kitchen Double Layer Sink Drain Hanging Bag Storage Rack",
        "Velvex Dishwashing Liquid Orange 1 Litre",
        "Dishwasher Salt 2kg",
        "Dishwasher Tablet 30-pack",
    ],
)
def test_dishwasher_rejects(title: str) -> None:
    assert parse_title(title, category="dishwashers").canonical_key is None


# ---------------------------------------------------------------------------
# Coffee machines
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key_prefix",
    [
        # Newmatic SKUs must produce distinct keys — the model-code tail
        # fallback guarantees that even when cups/watts aren't in the title.
        ("Newmatic BT-COF-103 Fully Automatic Coffee Maker Machine",
         "newmatic|bean-to-cup|bt-cof-103"),
        ("Newmatic BT-COF-203 Fully Automatic Coffee Maker Machine",
         "newmatic|bean-to-cup|bt-cof-203"),
        # Drip coffee with capacity
        ("Nunix Drip Coffee Maker 12 Cups 900W",
         "nunix|drip|12cups|900w"),
        # Espresso portable
        ("Nespresso Wireless Portable Espresso Coffee Machine",
         "nespresso|espresso"),
    ],
)
def test_coffee_machine_titles(title: str, expected_key_prefix: str) -> None:
    key = parse_title(title, category="coffee-machines").canonical_key
    assert key is not None
    assert key.startswith(expected_key_prefix), f"got {key!r}"


@pytest.mark.parametrize(
    "title",
    [
        # Accessories
        "Disposable Coffee Paper Filters 100 Pcs",
        "TodyJeyHo Coffee Espresso Tamper 51mm",
        "Frothing Pitcher, 31oz Espresso Milk Steaming Cup",
        "Universal Coffee Machine Cleaner & Descaling Tablets",
        "Home Small Hand-Crank Coffee Grinder, Manual",
        # Non-primary product (multi-function oven with a coffee side)
        "Nunix 12L Breakfast Maker Oven With Coffee Maker",
    ],
)
def test_coffee_machine_rejects(title: str) -> None:
    assert parse_title(title, category="coffee-machines").canonical_key is None


# ---------------------------------------------------------------------------
# Home & kitchen fixtures — sinks / countertops / hardware / etc.
# Newmatic-dominated categories; regex keys via brand + type + slugged tail.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,category",
    [
        # Every Newmatic SKU must key non-None so the shopper sees it.
        ("Newmatic Double 82 Ultra Deep Bowl Kitchen Sink", "kitchen-sinks-taps"),
        ("Newmatic Single 45cm Stainless Steel Kitchen Sink", "kitchen-sinks-taps"),
        ("Newmatic H84 Handcrafted Kitchen Sink", "kitchen-sinks-taps"),
        ("Newmatic CARRARA WHITE (Matt Finish) Sintered Stone Countertop", "countertops"),
        ("Newmatic Lauren Sintered Stone Countertop", "countertops"),
        ("Newmatic Motorized Pop Up Socket", "kitchen-hardware"),
        ("Newmatic Track Socket ATP Plugs", "kitchen-hardware"),
    ],
)
def test_fixture_titles_key(title: str, category: str) -> None:
    result = parse_title(title, category=category)
    assert result.canonical_key is not None, f"{category}: {title!r} failed to parse"
    assert result.brand == "newmatic"


def test_fixture_distinct_skus_get_distinct_keys() -> None:
    """The slugged-tail fallback must distinguish two SKUs that share the
    same brand + type — otherwise merging destroys them into one row."""
    a = parse_title(
        "Newmatic Double 82 Ultra Deep Bowl Kitchen Sink",
        category="kitchen-sinks-taps",
    ).canonical_key
    b = parse_title(
        "Newmatic Double 116 Ultra Deep Bowl Kitchen Sink",
        category="kitchen-sinks-taps",
    ).canonical_key
    assert a and b and a != b, f"collided: {a!r} == {b!r}"


@pytest.mark.parametrize(
    "title,category",
    [
        # Accessories in the sinks aisle
        ("Refillable Soap Dispenser 400ml", "kitchen-sinks-taps"),
        ("Bathroom Sink Plug Stopper Pop-Up Drain", "kitchen-sinks-taps"),
        ("Over The Sink Dish Drainer", "kitchen-sinks-taps"),
        # Cleaner in countertops
        ("Countertop Cleaner Spray 500ml", "countertops"),
        # Toilet paper is not a toilet
        ("Toilet Paper 12-roll pack", "toilets"),
        ("Toilet Cleaner Bleach 1L", "toilets"),
    ],
)
def test_fixture_rejects_accessory_noise(title: str, category: str) -> None:
    assert parse_title(title, category=category).canonical_key is None
