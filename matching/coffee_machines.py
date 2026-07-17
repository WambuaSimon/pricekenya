"""Coffee-machine matcher.

Kenyan retail titles range from KSh 5k portable espresso makers to
KSh 200k+ built-in super-automatic machines. Common families:
- Drip / filter coffee makers (Nunix, Ramtons, generic imports)
- Espresso machines (Delonghi, Nespresso, Krups, portable)
- Super-automatic / bean-to-cup (Newmatic BT-COF, Delonghi, Jura)
- French-press / manual pour-over (out of scope — no electric spec)

Rejects: filter papers, tampers, milk-frother pitchers, descaling
tablets, coffee grinders (they're their own thing), and any accessory
whose title makes clear it's not the brewing machine itself.
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("bean-to-cup", ("bean to cup", "bean-to-cup", "fully automatic coffee",
                     "fully-automatic coffee", "super automatic",
                     "super-automatic")),
    ("espresso", ("espresso machine", "espresso maker", "espresso coffee",
                  "capsule coffee", "pod coffee", "nespresso")),
    ("drip", ("drip coffee", "filter coffee", "pour over", "pour-over",
              "americano coffee")),
    # Bare "coffee machine" / "coffee maker" is the generic catch-all —
    # matched last so specific families win.
    ("coffee-machine", ("coffee machine", "coffee maker", "cafetière",
                        "coffee brewer")),
]

# Anything that's obviously not a brewing machine.
NON_COFFEE_MARKERS = (
    "coffee filter", "coffee papers", "filter paper", "paper filter",
    "coffee tamper", "espresso tamper", "milk frother",
    "milk pitcher", "frothing pitcher", "steam pitcher",
    "coffee grinder", "bean grinder", "burr grinder",  # separate device
    "coffee scale", "coffee timer",
    "descaling tablet", "descaling powder", "descaler",
    "coffee cleaner", "machine cleaner",
    "coffee cup", "coffee mug", "coffee glass",
    "coffee stirrer", "coffee spoon", "measuring spoon",
    "coffee capsule", "coffee pod refill", "reusable capsule",
    "coffee bean", "coffee ground", "ground coffee", "instant coffee",
    "coffee powder", "coffee syrup",
    "coffee table", "coffee tablecloth",
    # Multi-function ovens that happen to include a coffee side-feature
    # aren't primarily coffee machines.
    "breakfast maker oven", "breakfast oven with coffee",
    "multi-cooker with coffee",
    "spare part", "replacement filter",
)

# Wattage optional — coffee machines cluster 800W–2000W.
_WATTS_RE = re.compile(r"(\d{3,4})\s*(?:w\b|watts?)", re.IGNORECASE)
# Capacity: cup count OR millilitres.
_CUPS_RE = re.compile(r"(\d{1,2})\s*cups?\b", re.IGNORECASE)
_ML_RE = re.compile(r"(\d{3,4})\s*ml\b", re.IGNORECASE)


def _find_type(cleaned: str) -> str | None:
    for name, phrases in TYPE_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_watts(cleaned: str) -> int | None:
    for m in _WATTS_RE.finditer(cleaned):
        n = int(m.group(1))
        if 300 <= n <= 3000:
            return n
    return None


def _find_capacity(cleaned: str) -> tuple[str, int] | None:
    """Return (unit, value) — ('cups', n) or ('ml', n) — first plausible match."""
    m = _CUPS_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 20:
            return ("cups", n)
    m = _ML_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 100 <= n <= 3000:
            return ("ml", n)
    return None


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_COFFEE_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    coffee_type = _find_type(cleaned)
    if not coffee_type:
        return ParsedTitle()

    brand = find_brand(cleaned)
    if not brand:
        return ParsedTitle()

    condition = find_condition(cleaned)
    watts = _find_watts(cleaned)
    capacity = _find_capacity(cleaned)

    parts: list[str] = [slugify(brand), coffee_type]
    specs: dict = {"condition": condition, "type": coffee_type.replace("-", " ").title()}
    display_bits: list[str] = [
        brand.replace("-", " ").title(),
        coffee_type.replace("-", " ").title(),
        "Coffee Machine",
    ]

    if capacity:
        unit, val = capacity
        parts.append(f"{val}{unit}")
        specs[f"capacity_{unit}"] = val
        display_bits.append(f"{val} {unit.title()}")
    if watts:
        parts.append(f"{watts}w")
        specs["watts"] = watts
        display_bits.append(f"{watts}W")

    # Slugged tail from the title residue so two SKUs with the same
    # (brand, type) but different model codes (BT-COF-103 vs BT-COF-203)
    # don't collide-key. Only added when no spec (cups/ml/watts) was
    # extracted — if we already have a discriminating spec, the tail is
    # noise. Cap length to keep keys readable.
    if not (capacity or watts):
        residue = cleaned
        for tok in (
            brand,
            "coffee", "maker", "machine", "espresso", "capsule",
            "fully", "automatic", "portable", "electric",
            "brewer", "cafetière",
        ):
            residue = residue.replace(tok, " ")
        tail = slugify(residue)[:40] or None
        if tail:
            parts.append(tail)

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
