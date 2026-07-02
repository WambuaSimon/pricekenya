"""Regression tests for the appliance matchers (refrigerator, washer, cooking)."""

import pytest

from matching.normalize import parse_title


# ---------------------------------------------------------------------------
# Refrigerators
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Vision Plus 138L Double Door Refrigerator", "vision-plus|138l|double"),
        ("Vision Plus 220L Double Door Fridge", "vision-plus|220l|double"),
        (
            "Hisense REF094DR Fridge 94 Liters Single Door 94L Refrigerator",
            "hisense|94l|single",
        ),
        (
            "Ramtons RF/257- 2 Door Direct Cool Fridge - 213 Liters",
            "ramtons|213l|double",
        ),
        ("VON VRT-195DRHS Double Door Direct Cool Fridge - 195L", "von|195l|double"),
        ("K-ELEC 90L Single Door Fridge Silver", "k-elec|90l|single"),
    ],
)
def test_refrigerator_titles(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="refrigerators")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Refrigerator Door Seal 152cm Universal Replacement",
        "Chest Freezer 500L Deep Freeze",
        "Fridge Magnet Pack of 12",
        "Water Dispenser Hot and Cold",
    ],
)
def test_non_refrigerator_items_rejected(title: str) -> None:
    parsed = parse_title(title, category="refrigerators")
    assert parsed.canonical_key is None


def test_jumia_and_kilimall_hisense_94l_merge() -> None:
    """The Hisense 94L single-door fridge listed on both merchants must merge."""
    a = parse_title(
        "Hisense REF094DR Fridge 94 Liters Single Door 94ltr Refrigerator",
        category="refrigerators",
    ).canonical_key
    b = parse_title(
        "Hisense 94 Liters fridge single door Energy Saving REFO94DR Refrigerator",
        category="refrigerators",
    ).canonical_key
    assert a == b == "hisense|94l|single"


# ---------------------------------------------------------------------------
# Washers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        (
            "Vision Plus 8KG Slim Fully Automatic Front Load Washing Machine",
            "vision-plus|8kg|front|auto",
        ),
        (
            "Hisense WSQB753W 7.5Kg Twin Tub Top Load Washing Machine",
            "hisense|7.5kg|twin-tub|semi-auto",
        ),
        (
            "Haier 8kg Full Automatic Top Loader Washing Machines",
            "haier|8kg|top|auto",
        ),
        (
            "SmartPro 10kg Twin-tub Semi Automatic Washing Machine SWM-10TT",
            "smartpro|10kg|twin-tub|semi-auto",
        ),
    ],
)
def test_washer_titles(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="washers-dryers")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Washing Powder 5kg Detergent Fresh Scent",
        "Universal Washing Machine Drain Hose 2 Meters",
        "Laundry Basket Foldable 60L",
    ],
)
def test_non_washer_items_rejected(title: str) -> None:
    parsed = parse_title(title, category="washers-dryers")
    assert parsed.canonical_key is None


def test_washer_dryer_combo_marked() -> None:
    p = parse_title(
        "Skyworth F12446GDY Front Load 12KG, Automatic Washer With 8KG Dryer",
        category="washers-dryers",
    )
    assert "with-dryer" in p.canonical_key
    assert p.specs.get("has_dryer") is True


# ---------------------------------------------------------------------------
# Cooking (microwaves, cookers, ovens, hot plates)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Microwaves
        (
            "Hisense H20MOMS11 - 20 Liters Microwave - White (2YRs WRTY)",
            "hisense|microwave|20l",
        ),
        (
            "VON VAMS-20MGX - Manual Microwave Oven, Solo - 20L-Black",
            "von|microwave|20l|manual",
        ),
        (
            "Haier HMW28DBM - Digital Microwave Oven 900W, 28L - Black",
            "haier|microwave|28l|digital",
        ),
        (
            "Mika 20L Digital Microwave with Grill",
            "mika|microwave|20l|digital|grill",
        ),
        # Cookers
        ("Premier 4-Gas Cooker Plus Shelves", "premier|cooker|4-burner|gas"),
        (
            "VON Standing Cooker 60x90CM 5 Gas Burners Electric Oven",
            "von|cooker|5-burner|gas",
        ),
        (
            "Nunix 3+1 free standing electric oven cooker",
            "nunix|cooker|4-burner|electric",
        ),
        # Oven
        ("Roch 78L Built-In Electric Oven", "roch|oven|78l|electric"),
        # Hot plate
        (
            "AILYONS Electric double hot plate coil cooker 2000watts",
            "ailyons|hot-plate|2000w",
        ),
    ],
)
def test_cooking_titles(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="cooking")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Cookware Set 12 Piece Stainless Steel",
        "Cooker Hood Range 60cm Stainless Steel",
        "Microwave Rack Kitchen Organizer",
    ],
)
def test_non_cooking_items_rejected(title: str) -> None:
    parsed = parse_title(title, category="cooking")
    assert parsed.canonical_key is None


def test_microwave_capacity_optional() -> None:
    """Regression: 'Digital Glass Microwave' without a stated capacity should
    still index as brand + type + control, not get dropped."""
    p = parse_title("Ramtons RM/458 - Digital Glass Microwave", category="cooking")
    assert p.canonical_key == "ramtons|microwave|digital"
