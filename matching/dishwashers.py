"""Dishwasher matcher.

Split from washers-dryers on 2026-07-17. Dishwashers share almost nothing
with washing-machine buyer intent (KSh 60k–180k built-in vs KSh 20k–80k
freestanding washer), so lumping them was a bad UX.

Kenyan retail dishwasher titles cluster around:
- Brand: Newmatic, Bosch, Beko, Hotpoint, LG, Samsung, Ariston, Ramtons
- Configuration: built-in / freestanding / countertop / semi-integrated
- Capacity: place-settings (6, 8, 10, 12, 14, 15, 16)
- Optional: energy rating, program count

Rejects: dish racks, dish drainers, dishwashing liquid/paste — Jumia's
"dishwasher" search is dominated by those and none of them are a real
electric dishwasher.
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

# Configuration markers (order matters — check the more-specific "semi-
# integrated" before bare "integrated").
CONFIG_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("semi-integrated", ("semi-integrated", "semi integrated")),
    ("built-in", ("built-in", "built in", "fully-integrated", "fully integrated",
                  "integrated", "undercounter", "under-counter")),
    ("countertop", ("countertop", "counter-top", "counter top", "tabletop",
                    "table-top", "portable")),
    ("freestanding", ("free-standing", "free standing", "freestanding",
                      "standalone", "stand-alone")),
]

# "12 place settings", "14 place setting", "10-place"
_PLACE_SETTINGS_RE = re.compile(
    r"(\d{1,2})\s*(?:-?\s*place\s*settings?|place\s*setting)", re.IGNORECASE
)
# Fallback: bare "12 place" (some titles omit "settings")
_PLACE_BARE_RE = re.compile(r"(\d{1,2})\s*place\b", re.IGNORECASE)

# Program count occasionally appears — "5 programs", "8 wash programs"
_PROGRAMS_RE = re.compile(
    r"(\d{1,2})\s*(?:wash\s*)?programs?\b", re.IGNORECASE
)

# Title must contain one of these to qualify as a real dishwasher (not a
# rack, liquid, or non-electric accessory).
DISHWASHER_MARKERS = (
    "dishwasher", "dish washer", "dish-washer", "dish washing machine",
)

# Reject list: everything in a dishwasher category page that isn't a machine.
NON_DISHWASHER_MARKERS = (
    "dish rack", "dish drainer", "dish drying", "dish drying rack",
    "dish drying tray", "drying rack",
    "dishwashing liquid", "dishwashing paste", "dishwashing detergent",
    "dish washing liquid", "dish washing paste", "dish washing detergent",
    "dishwashing tablet", "dishwasher tablet",  # tablets are a consumable
    "dishwasher salt", "dishwasher rinse aid",
    "dishwasher cleaner", "dishwasher basket", "dishwasher rack replacement",
    "dish soap", "dish sponge",
    "dish organizer", "sink organizer",
    "spare part",
)


def _find_place_settings(cleaned: str) -> int | None:
    for m in _PLACE_SETTINGS_RE.finditer(cleaned):
        n = int(m.group(1))
        if 4 <= n <= 20:
            return n
    for m in _PLACE_BARE_RE.finditer(cleaned):
        n = int(m.group(1))
        if 4 <= n <= 20:
            return n
    return None


def _find_config(cleaned: str) -> str | None:
    for name, phrases in CONFIG_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_programs(cleaned: str) -> int | None:
    for m in _PROGRAMS_RE.finditer(cleaned):
        n = int(m.group(1))
        if 3 <= n <= 20:
            return n
    return None


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_DISHWASHER_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    if not any(m in cleaned for m in DISHWASHER_MARKERS):
        return ParsedTitle()

    brand = find_brand(cleaned)
    if not brand:
        return ParsedTitle()

    condition = find_condition(cleaned)
    place_settings = _find_place_settings(cleaned)
    config = _find_config(cleaned)
    programs = _find_programs(cleaned)

    parts: list[str] = [slugify(brand), "dishwasher"]
    specs: dict = {"condition": condition}
    display_bits: list[str] = [brand.replace("-", " ").title(), "Dishwasher"]

    if config:
        parts.append(config)
        specs["config"] = config.replace("-", " ").title()
        display_bits.append(specs["config"])
    if place_settings:
        parts.append(f"{place_settings}ps")
        specs["place_settings"] = place_settings
        display_bits.append(f"{place_settings} Place Settings")
    if programs:
        specs["programs"] = programs

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )
