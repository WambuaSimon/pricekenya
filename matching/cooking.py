"""Cooking-appliance matcher: microwaves, cookers, ovens, hobs.

The "cooking" leaf category collapses several device families that share
merchants and brands but have different spec profiles. We detect the device
type first from title keywords, then extract the relevant spec:

  microwave  → capacity_liters + control (digital/manual) + grill?
  cooker     → burners + fuel (gas/electric)
  oven       → capacity_liters
  hob        → burners + fuel
  hot plate  → burners + watts

The canonical key includes the type so a "20L microwave" doesn't merge with
"20L oven" even though the capacity matches.
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

# Type detection — ordered so more-specific / narrower phrases win.
# hot-plate must be checked before cooker because Kenyan retail titles often
# add "cooker" to hot-plate SKUs ("hot plate coil cooker").
TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("microwave", ("microwave",)),
    ("hot-plate", ("hot plate", "hotplate", "electric stove", "coil cooker")),
    ("cooker", ("standing cooker", "free standing cooker", "gas cooker",
                "electric cooker", "cooker",)),
    ("oven", ("built-in oven", "built in oven", "electric oven", "oven",)),
    ("hob", ("gas hob", "hob",)),
]

FUEL_GAS = ("gas cooker", "gas burner", "gas hob", "gas ", "lpg")
FUEL_ELECTRIC = ("electric cooker", "electric oven", "electric stove", "electric hot plate")
FUEL_INDUCTION = ("induction",)

CONTROL_DIGITAL = ("digital",)
CONTROL_MANUAL = ("manual",)
CONTROL_MECHANICAL = ("mechanical",)

MICROWAVE_GRILL = ("with grill", "grill combi", "microwave grill", "grill microwave")
MICROWAVE_CONVECTION = ("convection",)

# "20L", "20 L", "20 Liters", "78L", "20Ltrs"
_CAPACITY_RE = re.compile(
    r"(\d{1,3})\s*(?:l\b|ltr|liter|litre|lts)",
    re.IGNORECASE,
)
# "700W", "1000w", "2000 watts"
_WATTS_RE = re.compile(r"(\d{3,5})\s*(?:w\b|watts?)", re.IGNORECASE)
# "4 burner", "5-burner", "4 gas burners", "3+1", "4-Gas Cooker"
_BURNERS_RE = re.compile(r"\b(\d)[- +]?\s*(?:gas\s*)?(?:burner|hob|plate)s?", re.IGNORECASE)
_BURNERS_GAS_COOKER_RE = re.compile(r"\b(\d)[- ]*gas(?:\b|\s+cooker)", re.IGNORECASE)
_THREE_PLUS_ONE_RE = re.compile(r"3\s*\+\s*1")  # 3-gas-1-electric standing cookers

NON_COOKING_MARKERS = (
    "microwave stand", "microwave rack",
    "cooker hood", "range hood",
    "cooker knob", "cooker replacement",
    "cooking oil", "cooking pot", "cookware set",
    "egg tray", "egg cup",
    "spare part",
)


def _find_type(cleaned: str) -> str | None:
    for name, phrases in TYPE_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_fuel(cleaned: str) -> str | None:
    if any(m in cleaned for m in FUEL_INDUCTION):
        return "induction"
    if any(m in cleaned for m in FUEL_GAS):
        return "gas"
    if any(m in cleaned for m in FUEL_ELECTRIC):
        return "electric"
    return None


def _find_capacity_liters(cleaned: str) -> int | None:
    for m in _CAPACITY_RE.finditer(cleaned):
        n = int(m.group(1))
        if 5 <= n <= 200:
            return n
    return None


def _find_watts(cleaned: str) -> int | None:
    for m in _WATTS_RE.finditer(cleaned):
        n = int(m.group(1))
        if 200 <= n <= 6000:
            return n
    return None


def _find_burners(cleaned: str) -> int | None:
    # "3+1" is a common Kenyan standing-cooker layout = 4 burners total.
    if _THREE_PLUS_ONE_RE.search(cleaned):
        return 4
    m = _BURNERS_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 8:
            return n
    # Merchants often write "4-Gas Cooker" without "burner". Accept that form
    # as an implicit N-burner claim.
    m = _BURNERS_GAS_COOKER_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 8:
            return n
    return None


def _find_control(cleaned: str) -> str | None:
    if any(m in cleaned for m in CONTROL_DIGITAL):
        return "digital"
    if any(m in cleaned for m in CONTROL_MANUAL):
        return "manual"
    if any(m in cleaned for m in CONTROL_MECHANICAL):
        return "manual"
    return None


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_COOKING_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    brand = find_brand(cleaned)
    typ = _find_type(cleaned)
    if not (brand and typ):
        return ParsedTitle()

    specs: dict = {
        "type": typ.title(),
        "condition": find_condition(cleaned),
    }
    parts = [slugify(brand), typ]
    display_bits = [brand.replace("-", " ").title()]

    if typ == "microwave":
        capacity = _find_capacity_liters(cleaned)
        control = _find_control(cleaned)
        has_grill = any(m in cleaned for m in MICROWAVE_GRILL)
        # Capacity is preferred but not required — some titles just say
        # "Digital Glass Microwave" and we still want to index them.
        if capacity:
            parts.append(f"{capacity}l")
            specs["capacity_liters"] = capacity
            display_bits.append(f"{capacity}L")
        if control:
            parts.append(control)
            specs["control"] = control.title()
        if has_grill:
            parts.append("grill")
            specs["grill"] = True
        display_bits.append("Microwave")
        if has_grill:
            display_bits.append("with Grill")

    elif typ in ("cooker", "hob"):
        burners = _find_burners(cleaned)
        fuel = _find_fuel(cleaned)
        if not burners:
            return ParsedTitle()
        parts.append(f"{burners}-burner")
        if fuel:
            parts.append(fuel)
        specs["burners"] = burners
        if fuel:
            specs["fuel"] = fuel.title()
        display_bits += [f"{burners}-Burner", typ.title()]
        if fuel:
            display_bits.insert(-1, fuel.title())

    elif typ == "oven":
        capacity = _find_capacity_liters(cleaned)
        fuel = _find_fuel(cleaned)
        if not capacity:
            return ParsedTitle()
        parts.append(f"{capacity}l")
        if fuel:
            parts.append(fuel)
        specs["capacity_liters"] = capacity
        if fuel:
            specs["fuel"] = fuel.title()
        display_bits += [f"{capacity}L", "Oven"]

    elif typ == "hot-plate":
        watts = _find_watts(cleaned)
        burners = _find_burners(cleaned)
        if burners:
            parts.append(f"{burners}-burner")
            specs["burners"] = burners
        if watts:
            parts.append(f"{watts}w")
            specs["watts"] = watts
        display_bits += ["Hot Plate"]
        if watts:
            display_bits.append(f"({watts}W)")

    if specs["condition"] != "new":
        parts.append(specs["condition"])
        display_bits.append(specs["condition"].title())

    canonical_key = "|".join(parts)
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key=canonical_key,
        specs=specs,
        display_title=display,
    )
