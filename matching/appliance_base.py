"""Shared helpers for appliance matchers.

Kenyan appliance retail is brand-heavy but uses a fairly consistent set of
manufacturers across categories (fridges, washers, cookers). Rather than
duplicate the brand list per matcher, we share it here and let each category
add specialisations.
"""

from __future__ import annotations

import re

# Compound brands are checked as a phrase in the cleaned title first, so
# "Vision Plus" ends up as vision-plus, not vision.
APPLIANCE_COMPOUND_BRANDS: list[tuple[str, str]] = [
    ("vision plus", "vision-plus"),
    ("smart pro", "smartpro"),
    ("k elec", "k-elec"),
    ("k-elec", "k-elec"),
]

# Single-token brands. Includes the global names as well as the Kenyan and
# regional ones that dominate the entry / mid-tier appliance market.
APPLIANCE_BRANDS: set[str] = {
    # Global
    "samsung", "lg", "sony", "hisense", "tcl", "haier", "bosch", "whirlpool",
    "beko", "electrolux", "midea", "sharp", "toshiba", "panasonic", "skyworth",
    # Premium / imported brands common at Hotpoint
    "smeg", "ariete", "braun", "nutricook", "kenwood", "philips",
    "kitchenaid", "delonghi", "de'longhi", "moulinex", "tefal", "russell",
    "krups", "cuisinart", "morphy", "sunbeam", "black+decker", "sinbo",
    # Kenyan / regional / brand imports
    "vitron", "amtec", "ramtons", "bruhm", "von", "mika", "smartpro",
    "roch", "maxmo", "volsmart", "ecomax", "premier", "nunix", "sokany",
    "ailyons", "globalstar", "syinix", "smartec", "itel", "cube", "lyons",
    "solarmax", "nobel", "gld", "k-elec",
    "em",  # ElectroMate — appears bare or as "em"
    # Built-in kitchen appliance specialists whose product titles carry
    # only the SKU code (no brand token). Adding them so the required-
    # brand check in the cooking / refrigerator / washer matchers passes.
    "newmatic", "berklays", "scl",
}

CONDITION_KEYWORDS = {
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "renewed": "refurbished",
    "used": "used",
    "second hand": "used",
    "brand new": "new",
}


def find_brand(cleaned: str) -> str | None:
    """Return the canonical brand slug (or None). Multi-word brands checked first."""
    for phrase, canonical in APPLIANCE_COMPOUND_BRANDS:
        if phrase in cleaned:
            return canonical
    for tok in cleaned.split():
        tok = re.sub(r"[^a-z0-9-]", "", tok)
        if tok in APPLIANCE_BRANDS:
            return tok
    return None


def find_condition(cleaned: str) -> str:
    for kw, cond in CONDITION_KEYWORDS.items():
        if kw in cleaned:
            return cond
    return "new"
