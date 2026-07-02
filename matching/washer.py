"""Washing machine / dryer matcher.

Kenyan washer titles cluster around brand + capacity (kg) + load type
(twin-tub / top-load / front-load) + automation (fully vs semi automatic).
Twin-tub always means semi-automatic in this market so we don't repeat it.
Combo washer-dryers exist but are rare enough that a single capacity_kg
attribute plus a `has_dryer` flag suffices.
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

# "8KG", "8Kg", "10 kg", "7.5KG", "8kgs"
_CAPACITY_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:kgs?|kilogram)", re.IGNORECASE)

# Load type detection — order matters (check twin-tub before top-load since
# a twin-tub is technically top-loaded but sold as a distinct type).
LOAD_TWIN_TUB = ("twin tub", "twin-tub", "twintub")
LOAD_FRONT = ("front load", "front-load", "front loader", "front-loader")
LOAD_TOP = ("top load", "top-load", "top loader", "top-loader")

AUTO_MARKERS = ("fully automatic", "full automatic", "auto ", "automatic")
SEMI_AUTO_MARKERS = ("semi automatic", "semi-automatic", "semi-auto")

DRYER_MARKERS = (
    "washer dryer", "washer-dryer",
    "wash & dry", "wash and dry",
    "with dryer", "kg dryer",
    "wash & 7 kg dry", "wash & 8 kg dry", "wash and dry function",
)

NON_WASHER_MARKERS = (
    "vacuum cleaner",
    "cloth line", "clothesline",
    "washing powder", "detergent",
    "laundry bag", "laundry basket",
    "hose pipe", "hose only", "drain hose",
    "washer disc", "washing disc",
    "spin dryer",  # standalone spinners — different product
    "spare part",
)


def _find_capacity_kg(cleaned: str) -> float | None:
    for m in _CAPACITY_RE.finditer(cleaned):
        n = float(m.group(1))
        if 1 <= n <= 25:
            return n
    return None


def _find_load_type(cleaned: str) -> str | None:
    for phrase in LOAD_TWIN_TUB:
        if phrase in cleaned:
            return "twin-tub"
    for phrase in LOAD_FRONT:
        if phrase in cleaned:
            return "front"
    for phrase in LOAD_TOP:
        if phrase in cleaned:
            return "top"
    return None


def _find_automation(cleaned: str, load_type: str | None) -> str:
    # Twin-tub always semi-auto in practice.
    if load_type == "twin-tub":
        return "semi-auto"
    for m in SEMI_AUTO_MARKERS:
        if m in cleaned:
            return "semi-auto"
    for m in AUTO_MARKERS:
        if m in cleaned:
            return "auto"
    return "unknown"


def _fmt_capacity(kg: float) -> str:
    return str(int(kg)) if kg == int(kg) else str(kg)


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_WASHER_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    brand = find_brand(cleaned)
    capacity = _find_capacity_kg(cleaned)
    load_type = _find_load_type(cleaned)
    if not (brand and capacity and load_type):
        return ParsedTitle()

    automation = _find_automation(cleaned, load_type)
    has_dryer = any(m in cleaned for m in DRYER_MARKERS)
    condition = find_condition(cleaned)

    cap_str = _fmt_capacity(capacity)
    parts = [slugify(brand), f"{cap_str}kg", load_type]
    if automation != "unknown":
        parts.append(automation)
    if has_dryer:
        parts.append("with-dryer")
    if condition != "new":
        parts.append(condition)
    canonical_key = "|".join(parts)

    specs: dict = {
        "capacity_kg": capacity,
        "load_type": load_type.replace("-", " ").title(),
        "condition": condition,
    }
    if automation != "unknown":
        specs["automation"] = automation.replace("-", " ").title()
    if has_dryer:
        specs["has_dryer"] = True

    display_bits = [
        brand.replace("-", " ").title(),
        f"{cap_str}KG",
        specs["load_type"],
        specs.get("automation") or "",
        ("Washer-Dryer" if has_dryer else "Washing Machine"),
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
