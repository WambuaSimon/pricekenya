"""Two display-layer defects found while auditing image-less products.

Neither is an image problem; both were hiding behind one. Measured on prod
2026-10-27 across 9,809 products:

  209 products rendered a doubled brand   "Nokia Nokia 105"
   24 tablets filed under /c/phones       "Xiaomi Pad 8"
    8 smartwatches filed under /c/phones  "Samsung Watch 9"

Both are display-only fixes. `canonical_key` is left alone in each case
because it is the matching identity — rewriting it would re-bucket live
products and split them from their own listings.
"""

from __future__ import annotations

import pytest

from matching.match import (
    _pretty_title_for_phone,
    _refine_category,
    _strip_leading_brand,
)

# --------------------------------------------------------------------------
# Doubled brand


@pytest.mark.parametrize(
    "brand,model,expected",
    [
        ("nokia", "nokia 105", "105"),          # the observed shape
        ("honor", "honor 600 lite", "600 lite"),
        ("oneplus", "oneplus 15b", "15b"),
        ("NOKIA", "nokia 105", "105"),          # case-insensitive
        ("nokia", "NOKIA 105", "105"),
        ("honor", "600 lite", "600 lite"),      # already clean, untouched
        ("itel", "itel", "itel"),               # model IS the brand: keep it,
                                                # stripping would leave nothing
        ("oppo", "", ""),
    ],
)
def test_strip_leading_brand(brand, model, expected):
    assert _strip_leading_brand(brand, model) == expected


def test_pretty_title_no_longer_doubles_the_brand():
    assert (
        _pretty_title_for_phone("nokia", "nokia 105", {}) == "Nokia 105"
    )


def test_pretty_title_keeps_storage_suffix_while_deduping():
    assert (
        _pretty_title_for_phone("honor", "honor 600 lite", {"ram_gb": 8, "storage_gb": 256})
        == "Honor 600 Lite 8/256GB"
    )


def test_pretty_title_unaffected_when_model_is_already_clean():
    assert _pretty_title_for_phone("samsung", "a17", {"storage_gb": 128}) == "Samsung A17 128GB"


def test_brand_appearing_mid_model_is_not_stripped():
    """Only a LEADING duplicate is a parser artifact. A brand name inside the
    model is part of the product's name and must survive."""
    assert _strip_leading_brand("samsung", "galaxy samsung edition") == "galaxy samsung edition"


# --------------------------------------------------------------------------
# Device-class rerouting


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Xiaomi Pad 8", "tablets"),
        ("Oneplus Pad 11 12/256GB", "tablets"),
        ("Google Tab 10 8/128GB", "tablets"),
        ("Xiaomi Tablet 13", "tablets"),
        ("Samsung Watch 9", "phone-tablet-accessories"),
        ("Xiaomi Band 8", "phone-tablet-accessories"),
        ("Samsung Galaxy Fit 3", "phone-tablet-accessories"),
        ("Samsung A17", "phones"),            # an actual phone stays put
        ("Nokia 105", "phones"),
    ],
)
def test_refine_category_from_phones(title, expected):
    assert _refine_category("phones", title) == expected


@pytest.mark.parametrize("title", ["Padfone Infinity", "Watchdog Pro", "Fitbox 200"])
def test_substrings_do_not_trip_the_override(title):
    """Word-boundary matched. 'Padfone' is a phone; 'Watchdog' is not a watch."""
    assert _refine_category("phones", title) == "phones"


@pytest.mark.parametrize("source", ["tablets", "laptops", "audio", "tvs"])
def test_override_only_applies_to_phones_pages(source):
    """Narrow by design: only phones pages have shown this contamination, and
    a mis-parse elsewhere must not silently relocate a product."""
    assert _refine_category(source, "Xiaomi Pad 8") == source
