"""Small-appliances matcher: blenders, toasters, kettles, irons.

Each product family has very similar shape — brand + a small set of specs —
so we share one module with an expected-type parameter. Callers pass the
category-specific type so the matcher can validate the title actually
belongs to that leaf (a kettle listing that leaks into the toasters feed
gets rejected).
"""

from __future__ import annotations

import re

from matching.appliance_base import find_brand, find_condition
from matching.base import ParsedTitle, clean_title, slugify

# Type-name keywords ordered so more-specific phrases beat generic ones.
BLENDER_MARKERS = ("blender", "juicer", "food processor", "smoothie maker")
TOASTER_MARKERS = ("toaster", "toast oven", "bread toaster")
KETTLE_MARKERS = ("kettle", "cordless kettle", "electric kettle")
IRON_MARKERS = ("iron ", " iron", "steam iron", "flat iron", "dry iron",
                "press iron", "garment steamer")

# Per-type non-matching phrases — the item is in the merchant feed but isn't
# actually the appliance we're indexing.
NON_MATCHES: dict[str, tuple[str, ...]] = {
    "blender": (
        "blender bottle", "blender jug only", "blender base",
        "blender jar replacement", "blender blade", "spare part",
    ),
    "toaster": (
        "toaster stand", "toaster cover", "toaster bag", "spare part",
    ),
    "kettle": (
        "kettle stand", "kettle spare", "kettle base only",
        "kettle whistle", "spare part",
    ),
    "iron": (
        "iron board", "ironing board", "iron stand", "iron holder",
        "iron rest", "iron cover", "flat iron hair", "hair straightener",
        "curling iron", "spare part",
    ),
}

# "1.5L", "22L", "1.5 Liters", "22 Ltrs", etc. Two-digit needed for toaster
# ovens (typically 15L-40L) while blenders and kettles sit under 5L.
_CAPACITY_RE = re.compile(
    r"(\d{1,2}(?:\.\d)?)\s*(?:l\b|ltr|liter|litre|lts)",
    re.IGNORECASE,
)
# "700W", "1000w", "2000 watts"
_WATTS_RE = re.compile(r"(\d{3,5})\s*(?:w\b|watts?)", re.IGNORECASE)
# "2 slice", "4 slice", "2-slice"
_SLOTS_RE = re.compile(r"(\d)[- ]?(?:slot|slice|slice-slot)s?", re.IGNORECASE)

# Toaster sub-types
TOASTER_OVEN_MARKERS = ("toaster oven", "toast oven")

# Iron sub-types
IRON_TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("steam", ("steam iron", "steam station", "steam generator")),
    ("dry", ("dry iron",)),
    ("garment-steamer", ("garment steamer", "clothes steamer", "handheld steamer")),
    ("press", ("press iron", "ironing press", "pressing machine")),
]

# Kettle materials
KETTLE_MATERIAL_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("glass", ("glass kettle", "glass body")),
    ("stainless", ("stainless steel kettle", "stainless kettle", "stainless")),
    ("plastic", ("plastic kettle", "plastic body")),
]

# Blender sub-types
BLENDER_TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("juicer", ("juicer",)),
    ("food-processor", ("food processor",)),
    ("immersion", ("hand blender", "stick blender", "immersion blender")),
    ("personal", ("personal blender", "portable blender", "smoothie maker")),
    ("jug", ("jug blender", "countertop blender", "table blender")),
]


def _fmt_capacity(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def _find_capacity_liters(cleaned: str, max_l: float = 5.0) -> float | None:
    """Kettles / blenders / pop-up toasters sit under 5L; toaster ovens go
    higher, so callers pass a larger cap."""
    for m in _CAPACITY_RE.finditer(cleaned):
        n = float(m.group(1))
        if 0.3 <= n <= max_l:
            return n
    return None


def _find_watts(cleaned: str) -> int | None:
    for m in _WATTS_RE.finditer(cleaned):
        n = int(m.group(1))
        # Real small-appliance wattage: 500-3000W plausible; skip inflated claims.
        if 100 <= n <= 3500:
            return n
    return None


def _find_slots(cleaned: str) -> int | None:
    m = _SLOTS_RE.search(cleaned)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 6:
            return n
    return None


def _find_iron_type(cleaned: str) -> str | None:
    for name, phrases in IRON_TYPE_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_kettle_material(cleaned: str) -> str | None:
    for name, phrases in KETTLE_MATERIAL_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_blender_subtype(cleaned: str) -> str | None:
    for name, phrases in BLENDER_TYPE_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _title_looks_like(expected: str, cleaned: str) -> bool:
    markers = {
        "blender": BLENDER_MARKERS,
        "toaster": TOASTER_MARKERS,
        "kettle": KETTLE_MARKERS,
        "iron": IRON_MARKERS,
    }[expected]
    return any(m in cleaned for m in markers)


def parse_title(title: str, expected_type: str) -> ParsedTitle:
    if expected_type not in ("blender", "toaster", "kettle", "iron"):
        return ParsedTitle()

    cleaned = clean_title(title)

    # Reject items that leak in but aren't actually the appliance.
    for marker in NON_MATCHES.get(expected_type, ()):
        if marker in cleaned:
            return ParsedTitle()

    # Reject titles that don't even mention the expected appliance type. This
    # is what keeps a kettle out of the toasters feed.
    if not _title_looks_like(expected_type, cleaned):
        return ParsedTitle()

    brand = find_brand(cleaned)
    if not brand:
        return ParsedTitle()

    condition = find_condition(cleaned)
    specs: dict = {"type": expected_type.title(), "condition": condition}
    parts = [slugify(brand), expected_type]
    display_bits = [brand.replace("-", " ").title()]

    if expected_type == "blender":
        subtype = _find_blender_subtype(cleaned)
        capacity = _find_capacity_liters(cleaned)
        watts = _find_watts(cleaned)
        if subtype:
            parts.append(subtype)
            specs["subtype"] = subtype.replace("-", " ").title()
        if capacity:
            parts.append(f"{_fmt_capacity(capacity)}l")
            specs["capacity_liters"] = capacity
        if watts:
            specs["watts"] = watts
        display_bits.append((subtype or "Blender").replace("-", " ").title())
        if capacity:
            display_bits.append(f"{_fmt_capacity(capacity)}L")
        if watts:
            display_bits.append(f"({watts}W)")

    elif expected_type == "toaster":
        oven = any(m in cleaned for m in TOASTER_OVEN_MARKERS)
        slots = _find_slots(cleaned)
        watts = _find_watts(cleaned)
        # Toaster-ovens are keyed by capacity (higher range); pop-ups by slot count.
        capacity = _find_capacity_liters(cleaned, max_l=60.0) if oven else None
        if oven:
            parts.append("oven")
            specs["subtype"] = "Toaster Oven"
            if capacity:
                parts.append(f"{_fmt_capacity(capacity)}l")
                specs["capacity_liters"] = capacity
        elif slots:
            parts.append(f"{slots}-slot")
            specs["slots"] = slots
        if watts:
            specs["watts"] = watts
        display_bits.append("Toaster Oven" if oven else "Toaster")
        if slots and not oven:
            display_bits.append(f"{slots}-Slot")
        if capacity and oven:
            display_bits.append(f"{_fmt_capacity(capacity)}L")
        if watts:
            display_bits.append(f"({watts}W)")

    elif expected_type == "kettle":
        capacity = _find_capacity_liters(cleaned)
        material = _find_kettle_material(cleaned)
        watts = _find_watts(cleaned)
        if capacity:
            parts.append(f"{_fmt_capacity(capacity)}l")
            specs["capacity_liters"] = capacity
        if material:
            parts.append(material)
            specs["material"] = material.title()
        if watts:
            specs["watts"] = watts
        display_bits.append("Kettle")
        if capacity:
            display_bits.append(f"{_fmt_capacity(capacity)}L")
        if material:
            display_bits.append(material.title())
        if watts:
            display_bits.append(f"({watts}W)")

    elif expected_type == "iron":
        iron_type = _find_iron_type(cleaned) or "dry"
        watts = _find_watts(cleaned)
        parts.append(iron_type)
        specs["subtype"] = iron_type.replace("-", " ").title()
        if watts:
            specs["watts"] = watts
        display_bits.append(f"{iron_type.replace('-', ' ').title()} Iron")
        if watts:
            display_bits.append(f"({watts}W)")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    canonical_key = "|".join(parts)
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key=canonical_key,
        specs=specs,
        display_title=display,
    )
