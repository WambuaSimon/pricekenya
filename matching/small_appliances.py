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
# Model codes on Kenyan small appliances:
#   VBP501NLB, VSBT06MNX (Von)
#   RM/608, RM/764, RM/583 (Ramtons — slash-separated)
#   TYB-205, TYB-202-A, FY-B305 (Ailyons)
#   BLM45.240SS (Kenwood — dot inside the code)
#   H1STBWES2A, H15TBWES1A (Hisense — long middle-letter run + digit-letter tail)
#   AK-444, AK-500 (Nunix)
#   SBL-853B, SEL-954W (Smartpro)
#   LM242B28, LM438127, LM423 (Moulinex)
# The middle-letter run allows up to 8 chars (H1STBWES2A has 6). An optional
# separator+digit tail catches BLM45.240SS (dot then more digits then letters).
_MODEL_CODE_RE = re.compile(
    # The optional trailing digit run allows only NON-SPACE separators so
    # "AK-444 3" doesn't get glued into "AK4443" via the space, but
    # "BLM45.240SS" survives (dot inside the code).
    r"\b([a-z]{1,4}[-/. ]?[a-z]{0,3}\d{1,6}"
    r"[a-z]{0,8}(?:[-/.]?\d{1,4})?[a-z]{0,4})\b",
    re.IGNORECASE,
)

# Short English/marketing words that survive brand stripping and can attach
# to a nearby digit (e.g. "2 in 1" → "in1"). Rejected in _find_model_code
# so genuine SKU codes like "sn5" (short but not a stopword) still pass.
_MODEL_CODE_STOPWORDS: frozenset[str] = frozenset({
    "in", "on", "of", "for", "and", "or", "at", "by", "to", "vs", "up",
    "the", "a", "an", "not", "no", "with", "from", "yr", "yrs", "wrty",
    "yes", "hi", "lo",
})
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


def _find_model_code(cleaned: str, brand: str) -> str | None:
    """Extract a small-appliance SKU code.

    Same guardrails as the audio/refrigerator matchers: strip the brand
    token first (both the display form and the slug), reject codes that
    are just the brand, and reject long-letter+single-digit shapes that
    are usually marketing text ("blender 5", "watts 5"). Slash / dot /
    hyphen / space are all normalised away so RM/608 = RM-608 = RM 608.
    """
    brand_flat = brand.replace("-", "").replace(" ", "")
    brand_display = brand.replace("-", " ")
    stripped = re.sub(rf"\b{re.escape(brand_display)}\b", " ", cleaned, flags=re.IGNORECASE)
    stripped = re.sub(rf"\b{re.escape(brand)}\b", " ", stripped, flags=re.IGNORECASE)
    for m in _MODEL_CODE_RE.finditer(stripped):
        code = (
            m.group(1)
            .lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("/", "")
            .replace(".", "")
        )
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
        # Reject phrase remnants like "in1" from "2 in 1" or "of3" — the
        # alpha portion is a common English word, not an SKU prefix.
        alpha_prefix = "".join(c for c in code if c.isalpha())
        if alpha_prefix in _MODEL_CODE_STOPWORDS:
            continue
        return code
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
        model_code = _find_model_code(cleaned, brand)
        if subtype:
            parts.append(subtype)
            specs["subtype"] = subtype.replace("-", " ").title()
        # Only append the SKU code when the title actually has one. Watts
        # deliberately stays out of the canonical key — merchants often omit
        # it, and merging same-SKU listings across merchants matters more
        # than splitting by wattage. If we ever see enough shallow-key
        # blenders with distinct wattages this decision can be revisited.
        if model_code:
            parts.append(model_code)
            specs["model_code"] = model_code.upper()
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
