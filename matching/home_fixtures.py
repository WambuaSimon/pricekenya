"""Home & kitchen fixture matcher.

Introduced 2026-07-17 to catch Newmatic's built-in-kitchen catalog:
sinks/taps, countertops, splashbacks, kitchen hardware (power sockets),
utensils/kitchenware, plus bathroom toilets. These categories share a
title shape (brand + type + physical descriptor) but have wildly
different specs (a sink's key is "double 82cm", a countertop's key is
"carrara-white matt 15mm"), so we key permissively.

Design constraints:
- Kenyan retail for these categories is thin cross-merchant — Newmatic
  dominates. Aggressive cross-merchant merging isn't the priority; the
  priority is that every real fixture SKU gets *some* stable key so it
  lands on the site and is browseable.
- Titles are often terse SKU codes ("H84 Handcrafted Kitchen Sink").
  Fallback key = brand|type|slug-of-remaining-title so every SKU is
  keyable even when spec extraction fails.

Rejects: cleaning supplies, replacement parts, and accessories that
share a category page but aren't the fixture itself (soap dispensers
in the sinks aisle; grout in countertops; etc.).
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

# Per-leaf type markers. Ordered longest-first inside each family.
_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    "kitchen-sinks-taps": (
        "kitchen sink", "wash basin", "kitchen tap", "kitchen faucet",
        "kitchen mixer", "sink faucet", "sink tap", "sink mixer",
        "undermount sink", "undermounted sink", "sink",
    ),
    "countertops": (
        "sintered stone countertop", "quartz countertop",
        "granite countertop", "marble countertop", "solid surface countertop",
        "kitchen countertop", "countertop", "counter top", "worktop",
    ),
    "splashbacks": (
        "kitchen splashback", "glass splashback", "tile splashback",
        "splashback", "back splash", "backsplash",
    ),
    "kitchen-hardware": (
        "pop up socket", "pop-up socket", "power track socket",
        "track socket", "kitchen socket", "sink socket",
        "cabinet handle", "drawer handle", "cabinet knob", "drawer knob",
        "cabinet hinge", "drawer slide", "cabinet organizer",
    ),
    "utensils": (
        "cutlery set", "knife set", "kitchen knife", "chef knife",
        "cooking pot", "frying pan", "sauce pan", "saucepan",
        "cookware set", "utensil set", "kitchen tool set",
        "spatula", "ladle", "whisk",
        # Broad fallback — any single "utensil" mention. Type list must
        # be non-empty for the leaf to be considered.
        "utensil",
    ),
    "toilets": (
        "wall-hung toilet", "wall hung toilet", "back-to-wall toilet",
        "close-coupled toilet", "close coupled toilet",
        "one-piece toilet", "one piece toilet", "two-piece toilet",
        "two piece toilet",
        "smart toilet", "bidet toilet", "wc toilet", "toilet seat",
        "toilet bowl", "toilet",
    ),
}

# Common accessory noise per leaf.
_REJECT_MARKERS: dict[str, tuple[str, ...]] = {
    "kitchen-sinks-taps": (
        "soap dispenser", "sink drain plug", "sink strainer",
        "sink stopper", "sink cover", "sink protector",
        "dish drainer", "drying rack", "sink organizer",
        "sink mat", "sink bag",
        "faucet extender", "faucet adapter", "faucet aerator",
        "spare part", "replacement",
    ),
    "countertops": (
        "countertop cleaner", "countertop protector", "countertop mat",
        "countertop grill", "countertop oven", "countertop dishwasher",
        "spare part",
    ),
    "splashbacks": (
        "splashback cleaner", "spare part",
    ),
    "kitchen-hardware": (
        "spare part", "replacement", "screw only",
    ),
    "utensils": (
        "spare part", "replacement", "handle only",
    ),
    "toilets": (
        "toilet paper", "toilet cleaner", "toilet brush",
        "toilet freshener", "toilet spray", "toilet mat", "toilet rug",
        "toilet cover", "toilet seat cover only", "toilet lid cover",
        "spare part", "flush handle only", "flush valve",
    ),
}

# Dimension patterns (cm / mm / inches). Used opportunistically for the
# spec suffix — matcher stays permissive if none match.
_DIM_CM_RE = re.compile(r"(\d{2,3})\s*cm\b", re.IGNORECASE)
_DIM_MM_RE = re.compile(r"(\d{1,3})\s*mm\b", re.IGNORECASE)


def _find_type(cleaned: str, expected: str) -> str | None:
    for phrase in _TYPE_MARKERS.get(expected, ()):
        if phrase in cleaned:
            return phrase.replace(" ", "-").replace("--", "-")
    return None


def _find_dimension(cleaned: str) -> str | None:
    m = _DIM_CM_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 20 <= n <= 300:
            return f"{n}cm"
    m = _DIM_MM_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 5 <= n <= 100:
            return f"{n}mm"
    return None


def parse_title(title: str, expected_type: str) -> ParsedTitle:
    if expected_type not in _TYPE_MARKERS:
        return ParsedTitle()

    cleaned = clean_title(title)

    for marker in _REJECT_MARKERS.get(expected_type, ()):
        if marker in cleaned:
            return ParsedTitle()

    type_token = _find_type(cleaned, expected_type)
    if not type_token:
        return ParsedTitle()

    brand = find_brand(cleaned)
    if not brand:
        return ParsedTitle()

    condition = find_condition(cleaned)
    # Short slugged suffix from whatever remains after brand + type — gives
    # each SKU a stable key even when we can't extract a formal dimension.
    # Cap length so accidentally-long titles don't produce enormous keys.
    remainder = cleaned
    for tok in (brand, type_token.replace("-", " ")):
        remainder = remainder.replace(tok, " ")
    dim = _find_dimension(cleaned)
    tail = slugify(remainder)[:40] or None

    parts: list[str] = [slugify(brand), expected_type]
    specs: dict = {"condition": condition, "type": type_token.replace("-", " ").title()}
    display_bits: list[str] = [
        brand.replace("-", " ").title(),
        type_token.replace("-", " ").title(),
    ]

    if dim:
        parts.append(dim)
        specs["dimension"] = dim
        display_bits.append(dim)
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
