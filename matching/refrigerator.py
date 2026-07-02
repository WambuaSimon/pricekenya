"""Refrigerator matcher.

Kenyan retail fridge titles cluster around a small set of variables:
brand + capacity (liters) + door count. Model codes (REF094DR, VRT-195DRHS,
BCD-138) exist but aren't consistent enough to merge listings across
merchants — brand + size + door type is the right unit.

Freezers and combo units are rejected here; they belong to their own leaf.
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

# "138L", "138 L", "94 Liters", "128 Litres", "128ltr"
_CAPACITY_RE = re.compile(
    r"(\d{2,4})\s*(?:l\b|ltr|liter|litre|lts)",
    re.IGNORECASE,
)

DOOR_HINTS_DOUBLE = ("double door", "2 door", "2-door", "2door", "two door")
DOOR_HINTS_SINGLE = ("single door", "1 door", "1-door", "1door", "one door")
DOOR_HINTS_FRENCH = ("french door", "4 door", "quad door")
DOOR_HINTS_SBS = ("side by side", "side-by-side", "sbs")

# Reject the item if any of these appear — freezer-only or non-fridge items.
NON_REFRIGERATOR_MARKERS = (
    "chest freezer", "upright freezer",
    "water dispenser", "wine cooler",
    "refrigerator gasket", "refrigerator door seal",
    "fridge magnet", "mini bar",
    "showcase cooler", "beverage cooler",
    "spare part", "compressor",
)


def _find_capacity(cleaned: str) -> int | None:
    for m in _CAPACITY_RE.finditer(cleaned):
        n = int(m.group(1))
        if 40 <= n <= 900:  # plausible fridge capacity range
            return n
    return None


def _find_doors(cleaned: str) -> str | None:
    """Return 'single', 'double', 'french', 'sbs' or None if unclear."""
    for phrase in DOOR_HINTS_FRENCH:
        if phrase in cleaned:
            return "french"
    for phrase in DOOR_HINTS_SBS:
        if phrase in cleaned:
            return "sbs"
    for phrase in DOOR_HINTS_DOUBLE:
        if phrase in cleaned:
            return "double"
    for phrase in DOOR_HINTS_SINGLE:
        if phrase in cleaned:
            return "single"
    return None


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_REFRIGERATOR_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    brand = find_brand(cleaned)
    capacity = _find_capacity(cleaned)
    if not (brand and capacity):
        return ParsedTitle()

    doors = _find_doors(cleaned)
    condition = find_condition(cleaned)

    parts = [slugify(brand), f"{capacity}l"]
    if doors:
        parts.append(doors)
    if condition != "new":
        parts.append(condition)
    canonical_key = "|".join(parts)

    specs: dict = {
        "capacity_liters": capacity,
        "condition": condition,
    }
    if doors:
        specs["door_type"] = doors.upper() if doors == "sbs" else doors.title()

    display_bits = [
        brand.replace("-", " ").title(),
        f"{capacity}L",
        (specs.get("door_type") or "") + " Door" if doors else "",
        "Fridge",
        ("Refurbished" if condition == "refurbished" else ""),
    ]
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key=canonical_key,
        specs=specs,
        display_title=display,
    )
