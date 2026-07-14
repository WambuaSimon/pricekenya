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
# Fridge SKU shapes on Kenyan retail:
#   VRM-90DRAG, VRB-247NRAK, VRT-334NVAK (Von)
#   REF094DR, REF265DR, RS-12DR4SA (Hisense)
#   GN-B472PLMB, GL-B472PLMB (LG — letter prefix then letter-digit tail)
#   PM-50L (Premier)
# Two letter runs allowed before the digit run to cover LG's shape
# ("GN" + "-" + "B472PLMB"). Trailing digit + letter runs cover Hisense's
# "RS-12DR4SA" and Von's "VRM-90DRAG".
_MODEL_CODE_RE = re.compile(
    # Middle-letter run up to 8 chars covers Hisense H1STBWES2A shape.
    # Optional separator+digit tail catches Kenwood BLM45.240SS style —
    # non-space separator only, so "GN-B472PLMB 375L" doesn't get glued
    # into "GNB472PLMB375L" via the space before capacity.
    r"\b([a-z]{2,4}[-/. ]?[a-z]{0,3}\d{1,6}"
    r"[a-z]{0,8}(?:[-/.]?\d{1,4})?[a-z]{0,4})\b",
    re.IGNORECASE,
)

_MODEL_CODE_STOPWORDS: frozenset[str] = frozenset({
    "in", "on", "of", "for", "and", "or", "at", "by", "to", "vs", "up",
    "the", "a", "an", "not", "no", "with", "from", "yr", "yrs", "wrty",
})

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


def _find_model_code(cleaned: str, brand: str) -> str | None:
    """Return the fridge SKU (e.g. `vrm-90drag`) or None.

    Same guardrails the audio matcher uses: strip the brand token, reject
    the code if it IS the brand, require 3+ chars with at least one letter
    and one digit, and reject long-letter + single-digit shapes which are
    almost always marketing text like "wash 5" or "watts 5".
    """
    brand_flat = brand.replace("-", "").replace(" ", "")
    # `brand` is the canonical slug ("vision-plus"), but the cleaned title
    # uses the display form ("vision plus"). Try both. Also strip each
    # brand-word individually so leftover tokens don't get captured by the
    # code regex (e.g. "plus138l" from an unstripped "plus").
    brand_display = brand.replace("-", " ")
    stripped = re.sub(rf"\b{re.escape(brand_display)}\b", " ", cleaned, flags=re.IGNORECASE)
    stripped = re.sub(rf"\b{re.escape(brand)}\b", " ", stripped, flags=re.IGNORECASE)
    for m in _MODEL_CODE_RE.finditer(stripped):
        # Normalise all separators away so "RM/608", "RM-608", "RM 608"
        # merge into the same canonical fragment.
        code = m.group(1).lower().replace(" ", "").replace("-", "").replace("/", "")
        if code == brand_flat:
            continue
        if code.startswith(brand_flat) and len(code) > len(brand_flat):
            code = code[len(brand_flat):]
        letters = sum(1 for c in code if c.isalpha())
        digits = sum(1 for c in code if c.isdigit())
        if len(code) < 3 or letters == 0 or digits == 0:
            continue
        if digits <= 1 and letters > 3:
            continue
        alpha_prefix = "".join(c for c in code if c.isalpha())
        if alpha_prefix in _MODEL_CODE_STOPWORDS:
            continue
        return code
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
    model_code = _find_model_code(cleaned, brand)

    parts = [slugify(brand), f"{capacity}l"]
    # Model code goes in the key when we found one. Two listings for the
    # same SKU on different merchants share the code, so they merge; two
    # different SKUs at the same capacity (Hisense REF094DR vs RS-12DR4SA,
    # both 94L) split into distinct products instead of colliding.
    if model_code:
        parts.append(model_code)
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
    if model_code:
        specs["model_code"] = model_code.upper()

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
