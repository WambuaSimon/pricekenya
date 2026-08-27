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

# Combo washer-dryers advertise two figures: "15/8 Kg", "10.5/6kg", "9 / 6 KG".
# The FIRST is the wash load, the second the (smaller) dry load.
#
# _CAPACITY_RE alone reads these backwards. Scanning "15/8 Kg" it finds no
# "kg" after 15, matches "8 Kg" instead, and returns the DRY capacity as the
# machine's capacity. Measured on prod 2026-08-27: all 54 combo listings in
# washers-dryers were keyed on their dryer figure.
#
# On its own that is a bad spec. Combined with the dryer-marker gap below it
# was a collision: "LG 15/8 Kg Front Load Washer and Dryer" produced
# `lg|8kg|front`, identical to the genuine "LG 8KG Front Load Washing
# Machine", so a 238,995 combo merged into a 62,995 washer and the product
# page advertised a spread no shopper could act on.
_COMBO_CAPACITY_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*/\s*(\d{1,2}(?:\.\d)?)\s*(?:kgs?|kilogram)",
    re.IGNORECASE,
)

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

# The phrase-list above missed the most natural spellings — "Washer and
# Dryer", "Washer/Dryer", "Washer & Dryer" — so those listings came out with
# has_dryer=False and no `with-dryer` segment to keep them apart from a plain
# washer of the same capacity. One regex covers the whole family rather than
# another round of near-duplicate literals.
_DRYER_PHRASE_RE = re.compile(
    r"wash(?:er|ing\s+machine)?\s*(?:and|&|\+|/|-)\s*dry(?:er)?",
    re.IGNORECASE,
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


def _find_capacities(cleaned: str) -> tuple[float | None, float | None]:
    """Return (wash_kg, dry_kg). dry_kg is None unless a combo spec is present.

    A "15/8 kg" style figure is checked first and wins outright: when a title
    carries both a combo spec and a loose capacity elsewhere, the combo is the
    authoritative one.
    """
    combo = _COMBO_CAPACITY_RE.search(cleaned)
    if combo:
        wash, dry = float(combo.group(1)), float(combo.group(2))
        # Guard the orientation rather than trusting position: a dryer load is
        # never larger than the wash load on these machines, so a reversed
        # pair means we have misread something that is not a combo spec.
        if 1 <= wash <= 25 and 1 <= dry <= 25 and dry <= wash:
            return wash, dry

    for m in _CAPACITY_RE.finditer(cleaned):
        n = float(m.group(1))
        if 1 <= n <= 25:
            return n, None
    return None, None


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
    capacity, dryer_capacity = _find_capacities(cleaned)
    load_type = _find_load_type(cleaned)
    if not (brand and capacity and load_type):
        return ParsedTitle()

    automation = _find_automation(cleaned, load_type)
    # A combo capacity spec is itself proof of a dryer, and a more reliable
    # one than phrasing: "VON VWD-106FDDTX Front Load Washer/Dryer 10/6KG"
    # names the machine in three different ways across the catalog, but every
    # one of them carries the two-figure spec.
    has_dryer = (
        dryer_capacity is not None
        or bool(_DRYER_PHRASE_RE.search(cleaned))
        or any(m in cleaned for m in DRYER_MARKERS)
    )
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
    # Spec only, deliberately NOT part of the canonical key. Merchants list
    # the same machine as both "10kg Wash & Dry" and "10/7kg", so keying on
    # the dry figure would split one product in two — the opposite of the
    # merge this fix exists to prevent. `with-dryer` already separates a combo
    # from a plain washer, which is the distinction that was missing.
    if dryer_capacity is not None:
        specs["dryer_capacity_kg"] = dryer_capacity

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
