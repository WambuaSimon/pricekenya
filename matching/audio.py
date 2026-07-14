"""Audio matcher: earbuds, headphones, speakers, soundbars, home theatres, MP3 players.

The audio leaf covers a wide range of device families. We detect the type from
title keywords, then extract type-appropriate specs. Kenyan retail dominates
the home-theatre / subwoofer bucket (Lyons, AILYONS, Vitron, Amtec) with
inflated watt claims (9000W, 20000W speakers), so wattage is captured only
for display, never in the canonical key. Model codes (LYS3602, HS5100) are
included in the canonical key when present because same-brand same-channel
listings are usually different SKUs (LYS3602 vs LYS3604 vs LYS3605).
"""

from __future__ import annotations

import re

from matching.appliance_base import find_condition
from matching.base import ParsedTitle, clean_title, slugify

# Two-word brands first — the appliance list mostly transfers, plus a few
# audio-only names.
COMPOUND_BRANDS: list[tuple[str, str]] = [
    ("vision plus", "vision-plus"),
    ("smart pro", "smartpro"),
    ("jbl", "jbl"),
]

KNOWN_BRANDS = {
    # Global
    "samsung", "lg", "sony", "hisense", "tcl", "haier", "bose", "sennheiser",
    "beats", "jbl", "harman", "kardon", "philips", "sharp", "toshiba",
    "panasonic", "skyworth", "xiaomi", "oraimo", "havit", "anker",
    # Kenyan / regional / imports
    "vitron", "amtec", "ramtons", "bruhm", "von", "mika", "smartpro",
    "roch", "volsmart", "ecomax", "premier", "nunix", "sokany", "ailyons",
    "globalstar", "syinix", "smartec", "itel", "cube", "lyons", "solarmax",
    "nobel", "gld", "amitec", "amv", "euroken", "wk", "boat", "boult",
    "boyi",
}

TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("soundbar", ("soundbar", "sound bar")),
    ("home-theatre", ("home theatre", "home theater", "subwoofer", "sub woofer",
                      "sub-woofer", "multimedia speaker system")),
    ("party-speaker", ("party speaker", "pa speaker", "outdoor speaker",
                       "trolley speaker")),
    ("earbuds", ("earbuds", "tws", "in-ear", "in ear", "true wireless",
                 "wireless earphones")),
    ("headphones", ("headphones", "headset", "over-ear", "over ear",
                    "on-ear", "on ear", "headphone")),
    ("mp3-player", ("mp3 player", "mp4 player", "mp3/mp4")),
    ("speaker", ("bluetooth speaker", "bt speaker", "portable speaker",
                 "speaker",)),
]

NON_AUDIO_MARKERS = (
    "usb charger", "wall charger", "wall plug", "fast charger",
    "phone charger", "type-c charger", "type c charger", "wireless charger",
    "car charger", "power bank", "powerbank",
    "hdmi cable", "aux cable", "audio cable only", "vga cable",
    "speaker bracket", "speaker stand only", "microphone stand",
    "usb adapter", "bluetooth adapter",  # not the speaker
    "ear cushion", "ear pad replacement",
    "usb hub", "extension cable",
)

# Channel config: 2.1CH, 5.1 CH, 2.0CH, 7.1 CH
_CHANNELS_RE = re.compile(r"(\d)\.(\d)\s*ch", re.IGNORECASE)
# Watts — only kept for display, and only when plausible.
_WATTS_RE = re.compile(r"(\d{2,5})\s*w(?:atts?)?\b", re.IGNORECASE)
# Model codes — brand-specific SKUs like LYS3602, HS5100, VP2121SB, ELP2406K,
# and JBL "Bar 800MK2" (digit-alpha-digit tail).
# Require enough characters + digits to avoid grabbing things like "2.1" or "5G".
_MODEL_CODE_RE = re.compile(
    r"\b([a-z]{2,6}[- ]?\d{2,6}[a-z]{0,3}\d{0,3})\b", re.IGNORECASE
)

WIRELESS_MARKERS = ("wireless", "bluetooth", "bt ", " bt", "tws")


def _find_brand(cleaned: str) -> str | None:
    for phrase, canonical in COMPOUND_BRANDS:
        if phrase in cleaned:
            return canonical
    for tok in cleaned.split():
        tok = re.sub(r"[^a-z0-9-]", "", tok)
        if tok in KNOWN_BRANDS:
            return tok
    return None


def _find_type(cleaned: str) -> str | None:
    for name, phrases in TYPE_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_channels(cleaned: str) -> str | None:
    m = _CHANNELS_RE.search(cleaned)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return None


def _find_watts(cleaned: str) -> int | None:
    for m in _WATTS_RE.finditer(cleaned):
        n = int(m.group(1))
        # Filter marketing inflation. Real consumer speakers rarely exceed 1000W;
        # 3000W is a generous ceiling for the Kenyan retail claims we accept.
        if 5 <= n <= 3000:
            return n
    return None


def _find_model_code(cleaned: str, brand: str) -> str | None:
    """Pick the first model-code-shaped token that isn't the brand itself."""
    for m in _MODEL_CODE_RE.finditer(cleaned):
        code = m.group(1).lower().replace(" ", "-").replace("-", "")
        if code == brand.replace("-", ""):
            continue
        # Codes with only 2 letters + 2 digits are usually not real SKUs — skip
        # them unless they look distinctive (mix of letters + digits + letters).
        letters = sum(1 for c in code if c.isalpha())
        digits = sum(1 for c in code if c.isdigit())
        if letters < 2 or digits < 3:
            continue
        return code
    return None


def _is_wireless(cleaned: str) -> bool:
    return any(kw in cleaned for kw in WIRELESS_MARKERS)


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_AUDIO_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    brand = _find_brand(cleaned)
    typ = _find_type(cleaned)
    if not (brand and typ):
        return ParsedTitle()

    condition = find_condition(cleaned)
    specs: dict = {"type": typ.replace("-", " ").title(), "condition": condition}
    parts = [slugify(brand), typ]
    display_bits = [brand.replace("-", " ").title()]

    if typ in ("soundbar", "home-theatre", "party-speaker", "speaker"):
        channels = _find_channels(cleaned)
        model_code = _find_model_code(cleaned, brand)
        watts = _find_watts(cleaned)
        if model_code:
            parts.append(model_code)
            specs["model_code"] = model_code.upper()
        elif channels:
            parts.append(channels)
        if channels:
            specs["channels"] = channels
        if watts:
            specs["watts"] = watts
# Display: model code (if any) upgrades the generic type name so
        # a "JBL Bar 800MK2 Soundbar" doesn't render as just "Jbl Soundbar".
        display_bits.append(typ.replace("-", " ").title())
        if model_code:
            display_bits.append(model_code.upper())
        if channels:
            display_bits.append(f"{channels}CH")
        if watts:
            display_bits.append(f"{watts}W")

    elif typ in ("earbuds", "headphones"):
        model_code = _find_model_code(cleaned, brand)
        wireless = _is_wireless(cleaned)
        if model_code:
            parts.append(model_code)
            specs["model_code"] = model_code.upper()
        parts.append("wireless" if wireless else "wired")
        specs["connectivity"] = "Wireless" if wireless else "Wired"
        display_bits.append(typ.title())
        display_bits.append(specs["connectivity"])

    elif typ == "mp3-player":
        model_code = _find_model_code(cleaned, brand)
        if model_code:
            parts.append(model_code)
            specs["model_code"] = model_code.upper()
        display_bits.append("MP3 Player")

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
