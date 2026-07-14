"""Tablet-category title parser.

Very similar shape to phones (brand + model + storage + RAM), but with a
tablet-specific brand list and model patterns. Kept as its own module so a
phone-brand-matched title (e.g. "Tecno Spark 30C") doesn't accidentally leak
into the tablets feed when a scraper misroutes, and vice-versa.

Canonical key format:
  <brand>|<model>[|<storage_gb>][|<ram_gb>]

e.g. "Samsung Galaxy Tab S9 FE 8GB 128GB" → "samsung|tab-s9-fe|128|8"
     "Apple iPad Air 11-inch (M2) 128GB"  → "apple|ipad-air-11|128"
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title, slugify

# Brands that make tablets. Some overlap with phones (Samsung, Apple, Xiaomi,
# Huawei, Honor) — the module-level dispatch keeps them semantically separate
# so a phone titled "Samsung Galaxy A55" doesn't leak into tablets even though
# Samsung is in this list.
KNOWN_BRANDS = {
    # Global
    "apple", "ipad", "samsung", "huawei", "matepad", "mediapad", "honor",
    "xiaomi", "redmi", "poco", "lenovo", "amazon", "kindle", "fire",
    "microsoft", "surface", "asus", "acer", "hp", "dell", "google",
    "oneplus", "nokia", "tcl", "alcatel", "realme", "oppo", "vivo",
    "blackview", "doogee", "cubot", "chuwi", "teclast", "onn", "wacom",
    # Kenyan / regional / imports commonly seen at Jumia / Kilimall
    "x-tigi", "xtigi", "modio", "atouch", "atouch-tablet", "cctronics",
    "wintouch", "meanit", "meanit-tablet", "iconix", "coby", "smarter",
    "vsun", "reeder", "digma",
}

BRAND_ALIASES = {
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "ipad": "apple",
    "matepad": "huawei",
    "mediapad": "huawei",
    "surface": "microsoft",
    "fire": "amazon",
    "kindle": "amazon",
    "pixel": "google",
    "xtigi": "x-tigi",
    "atouch-tablet": "atouch",
    "meanit-tablet": "meanit",
}

# Markers whose presence confirms the listing is actually a tablet. If none
# match, we reject the title — this keeps phones from leaking into the
# tablets feed even when the scraper misroutes them.
_TABLET_MARKERS = (
    "tablet", "ipad", "matepad", "mediapad", "galaxy tab", "tab a", "tab s",
    "mi pad", "redmi pad", "poco pad", "lenovo tab", "fire hd", "fire max",
    "surface pro", "surface go", "kindle", "e-reader", "ereader",
    # Common lower-tier tablet brands don't always mention "tablet" in the
    # title, so the model-line hint alone is a valid signal.
    "x-tigi kids", "atouch kids", "kids tablet",
)

# Non-tablet leak: accessories that live in the same merchant feed but
# aren't actually tablets.
#
# The rejection using this list is GATED on the two-signal rule (see
# parse_title below): the marker must match AND we must have failed to
# extract storage_gb/ram_gb. Real tablets always list at least one; a
# case or keyboard listing lists neither. This is what lets bundle
# language ("Surface Pro with Keyboard", "Redmi Pad SE (Free Case)")
# still parse as the real tablet.
_NON_TABLET_MARKERS = (
    # Cases / covers — specific accessory subtypes
    " case", " cover", "flip case", "flip cover", "wallet case",
    "silicone case", "leather case",
    # Screen protection
    "screen protector", "screen guard", "tempered glass", "hydrogel",
    "privacy film", "phone skin", "vinyl skin",
    # Pens / styluses (as accessories) — pen slot is a real tablet feature
    # ("with S Pen slot"), so we match "s pen only", "pen only",
    # "stylus pen" (product), not " stylus" bare.
    "stylus pen", "s pen only",
    # Keyboards / peripherals sold as accessories
    "keyboard cover", "keyboard case", "keyboard folio",
    "tablet keyboard",
    # Mounts, stands, holders sold standalone
    "tablet stand", "tablet holder", "tablet mount", "tablet cradle",
    "car mount", "wall mount",
    # Chargers / cables / adapters
    "wall charger", "usb charger", "fast charger", "wireless charger",
    "charging cable", "usb cable", "lightning cable", "type-c cable",
    "power adapter", "usb adapter",
    # Bags / sleeves / pouches sold as accessories
    "tablet sleeve", "tablet pouch", "tablet bag",
    # Repair / spare parts
    "spare part", "replacement screen", "screen replacement",
    "battery replacement",
    # Non-tablet items in the tablet feed
    "graphics tablet", "drawing tablet", "writing tablet",
    "children's tablet toy", "learning tablet",  # kids-toy tablets are noise
)

NOISE_TOKENS = {"tablet", "smartphone", "phone", "5g", "4g", "lte", "dual", "sim"}

_STORAGE_PAIR_RE = re.compile(
    r"(?<!\.)(?P<a>\d{1,3})\s*(?:gb)?\s*[+/]\s*(?P<b>\d{2,4})\s*(?:gb)?",
    re.IGNORECASE,
)
_STORAGE_MIN_GB, _STORAGE_MAX_GB = 16, 4096
_RAM_MIN_GB, _RAM_MAX_GB = 1, 32  # tablets do ship with 1-2GB entry SKUs
_ALL_GB_RE = re.compile(r"(\d{1,4})\s*gb", re.IGNORECASE)
_MODEL_RE = re.compile(
    r"\b([a-z]+\s*\d{1,4}\s*[a-z]?(?:\s*pro|\s*plus|\s*ultra|\s*lite|\s*fe|\s*\+)?)\b",
    re.IGNORECASE,
)
_TIGHTEN_MODEL_RE = re.compile(r"(\d+)\s+([a-z])\b", re.IGNORECASE)

# Screen size — a tablet spec buyers care about (7", 10.1", 11", 12.9").
_SIZE_RE = re.compile(
    r"\b(\d{1,2}(?:\.\d)?)\s*(?:\"|inch(?:es)?|-inch)\b",
    re.IGNORECASE,
)


def _find_brand(cleaned: str) -> tuple[str | None, str | None]:
    for token in cleaned.split():
        tok = re.sub(r"[^a-z0-9-]", "", token)
        if tok in KNOWN_BRANDS:
            return BRAND_ALIASES.get(tok, tok), tok
    return None, None


def _find_storage(cleaned: str) -> tuple[int | None, int | None]:
    m = _STORAGE_PAIR_RE.search(cleaned)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        ram, storage = sorted([a, b])
        if _STORAGE_MIN_GB <= storage <= _STORAGE_MAX_GB and _RAM_MIN_GB <= ram <= _RAM_MAX_GB:
            return storage, ram
    matches = [int(x) for x in _ALL_GB_RE.findall(cleaned)]
    if not matches:
        return None, None
    big = [x for x in matches if x >= _STORAGE_MIN_GB]
    small = [x for x in matches if _RAM_MIN_GB <= x < _STORAGE_MIN_GB]
    storage = max(big) if big else None
    ram = min(small) if small else None
    return storage, ram


def _find_size(cleaned: str) -> float | None:
    for m in _SIZE_RE.finditer(cleaned):
        n = float(m.group(1))
        if 5 <= n <= 15:
            return n
    return None


def _strip_noise(cleaned: str) -> str:
    parts = [t for t in cleaned.split() if t and t not in NOISE_TOKENS]
    return " ".join(parts)


def _find_model(cleaned: str) -> str | None:
    text = _strip_noise(cleaned)
    m = _MODEL_RE.search(text)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1)).strip()
    return _TIGHTEN_MODEL_RE.sub(r"\1\2", raw)


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    # Positive-signal check: must look like a tablet or the scraper leaked
    # something else in (a phone, a laptop, a case) that we shouldn't index.
    if not any(m in cleaned for m in _TABLET_MARKERS):
        return ParsedTitle()

    brand, _ = _find_brand(cleaned)
    storage, ram = _find_storage(cleaned)
    model = _find_model(cleaned)

    # Reject tablet-adjacent accessories: marker match AND no tablet-spec
    # signal (no storage_gb, no ram_gb). Real tablets always list at least
    # one; a "Lenovo Tab M11 (with Case) 128GB" bundle listing has 128 in it
    # and so keeps parsing as the real tablet.
    if any(m in cleaned for m in _NON_TABLET_MARKERS) and not (storage or ram):
        return ParsedTitle()
    size = _find_size(cleaned)

    specs: dict = {}
    if storage:
        specs["storage_gb"] = storage
    if ram:
        specs["ram_gb"] = ram
    if size:
        specs["screen_inches"] = size

    if not (brand and model):
        return ParsedTitle(brand=brand, model=model, specs=specs)

    parts = [slugify(brand), slugify(model)]
    if size:
        # Screen size is a real differentiator for tablets — an iPad Air 11
        # and an iPad Air 13 are separate products.
        parts.append(f"{size:g}in")
    if storage:
        parts.append(str(storage))
    if ram:
        parts.append(str(ram))

    return ParsedTitle(
        brand=brand,
        model=model,
        canonical_key="|".join(parts),
        specs=specs,
    )
