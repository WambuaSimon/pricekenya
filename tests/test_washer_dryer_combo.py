"""A washer-dryer combo must not collapse into a plain washer.

Two defects in matching/washer.py combined into one product-merge bug.

`_CAPACITY_RE` reads a combo spec backwards: scanning "15/8 Kg" it finds no
"kg" after 15, matches "8 Kg", and returns the DRY capacity as the machine's
capacity. Separately, DRYER_MARKERS listed "washer dryer" and "washer-dryer"
but not "washer and dryer", so the combo also lost its `with-dryer` segment.

Together, "LG 15/8 Kg Front Load Washer and Dryer" produced `lg|8kg|front` —
byte-identical to the genuine "LG 8KG Front Load Washing Machine". A 238,995
combo merged into a 62,995 washer, and the product page then advertised a
176,000 "saving" no shopper could act on.

Measured on prod 2026-08-27: all 54 combo listings in washers-dryers were
keyed on their dryer figure; four or more had no `with-dryer` segment either
and so were colliding with real plain washers.
"""

from __future__ import annotations

import pytest

from matching.washer import parse_title

# Verbatim from production listings.
LG_COMBO = "LG 15/8 Kg Front Load Washer and Dryer F0Z6DRP24 Essence Graphite"
LG_PLAIN_A = "LG F4J3TYG6J Front Load Washing Machine, 8KG - 6 Motion Direct Drive"
LG_PLAIN_B = "LG YG6J - 8Kg Front Load Washing Machine, Black (2YRs WRTY)"


def test_combo_does_not_collide_with_plain_washer():
    """The regression itself: these are different machines at wildly
    different prices and must not share a canonical key."""
    combo = parse_title(LG_COMBO).canonical_key
    plain = parse_title(LG_PLAIN_A).canonical_key

    assert combo != plain
    assert combo == "lg|15kg|front|with-dryer"
    assert plain == "lg|8kg|front"


def test_genuine_duplicates_still_merge():
    """The fix must not over-split: two listings of the same 8kg washer from
    different merchants still have to land on one product."""
    assert parse_title(LG_PLAIN_A).canonical_key == parse_title(LG_PLAIN_B).canonical_key


@pytest.mark.parametrize(
    "title,expected_wash,expected_dry",
    [
        (LG_COMBO, 15.0, 8.0),
        ("VON VWD-106FDDTX Front Load Washer/Dryer - 10/6KG", 10.0, 6.0),
        ("Syinix 10/7KG Washer and Dryer Combo Front Load", 10.0, 7.0),
        ("LG 20/12KG F3L2CRV2T Front Load Washer Dryer", 20.0, 12.0),
        ("Hisense Washing Machine 10.5/6kg Wash & Dry Front Load", 10.5, 6.0),
        ("Von Vawd-906Fvk Front Load Washer Dryer 9/6 KG", 9.0, 6.0),
    ],
)
def test_combo_capacity_is_the_wash_load(title, expected_wash, expected_dry):
    """The first figure is the wash load. Every one of these was previously
    keyed on the second."""
    specs = parse_title(title).specs
    assert specs["capacity_kg"] == expected_wash
    assert specs["dryer_capacity_kg"] == expected_dry
    assert specs["has_dryer"] is True


@pytest.mark.parametrize(
    "phrasing",
    [
        "LG 9KG Front Load Washer and Dryer",
        "LG 9KG Front Load Washer & Dryer",
        "LG 9KG Front Load Washer/Dryer",
        "LG 9KG Front Load Washer-Dryer",
        "LG 9KG Front Load Wash and Dry",
        "LG 9KG Front Load Washing Machine and Dryer",
    ],
)
def test_dryer_is_detected_across_phrasings(phrasing):
    """The old literal list covered only two of these six spellings."""
    assert parse_title(phrasing).specs.get("has_dryer") is True
    assert parse_title(phrasing).canonical_key == "lg|9kg|front|with-dryer"


def test_plain_washer_has_no_dryer_spec():
    specs = parse_title(LG_PLAIN_A).specs
    assert "has_dryer" not in specs
    assert "dryer_capacity_kg" not in specs


def test_dry_capacity_stays_out_of_the_canonical_key():
    """Merchants list the same machine both ways: "10kg Wash & Dry" and
    "10/7kg". Keying on the dry figure would split one product in two — the
    opposite of the merge this fix prevents.
    """
    with_figures = parse_title("Hisense 10/7kg Front Load Wash & Dry Washing Machine")
    without = parse_title("Hisense 10Kg Wash & Dry Front Load Washing Machine WD3Q1043BT")

    assert with_figures.canonical_key == without.canonical_key
    # The dry figure is still captured, just as a spec rather than identity.
    assert with_figures.specs["dryer_capacity_kg"] == 7.0
    assert "dryer_capacity_kg" not in without.specs


def test_reversed_pair_is_not_treated_as_a_combo():
    """A dryer load is never larger than the wash load. A reversed pair means
    we have misread something that is not a combo spec, so fall back to the
    plain single-capacity read rather than trusting position.
    """
    parsed = parse_title("Roch 6/12KG Front Load Washing Machine")
    assert parsed.specs.get("dryer_capacity_kg") is None
