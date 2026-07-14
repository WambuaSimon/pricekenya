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
# JBL "Bar 800MK2", LG "SN5", TCL "Q65H", Vitron "V61SB", Sony "HT-S350",
# Samsung "HW-Q800D", Amtec "AM-01".
#
# Allow single-letter prefix (V61SB, Q65H, S45H) — Kenyan retail SKUs
# routinely use 1-3 letters + short digit run. Keep the length filter below
# tight enough to reject noise like "5G", "2.1CH", "IPX7".
_MODEL_CODE_RE = re.compile(
    r"\b([a-z]{1,6}[- ]?\d{1,6}[a-z]{0,4}\d{0,4})\b", re.IGNORECASE
)

# Named product families per brand — the "marketing name + generation" that
# consumer-audio brands use in place of numeric SKUs. Without this list,
# JBL "Flip 6" / "Charge 5" / "Xtreme 4" / "PartyBox 300" all fail the
# _MODEL_CODE_RE minimum-digit test and collapse into `jbl|speaker`.
#
# Rules:
#   - Family words are single-token (no spaces). Multi-word marketing names
#     like "SoundLink Flex" appear as one entry each ("soundlink").
#   - Match longest first so "SoundLink" wins over a hypothetical "Sound".
#   - Version can be: digits ("6"), a keyword ("Encore", "Plus", "Pro",
#     "Max"), a digit-letter-digit tail ("800MK2"), or absent (just the
#     family name — e.g. bare "JBL Go" is a real SKU distinct from "Go 4").
BRAND_FAMILIES: dict[str, tuple[str, ...]] = {
    "jbl": (
        # Portable / party
        "flip", "charge", "xtreme", "pulse", "clip", "boombox", "partybox",
        "go", "wind", "authentics",
        # Earbuds / headphones
        "tune", "live", "reflect", "endurance", "vibe", "wave",
        # Home audio
        "bar", "quantum", "spinner",
    ),
    "sony": (
        "srs", "wh", "wf", "linkbuds", "ult",
    ),
    "bose": (
        "soundlink", "quietcomfort", "sport", "revolve", "portable",
        "smart",
    ),
    "anker": (
        "soundcore",  # then family "Motion", "Boom", "Frames" etc.
    ),
    "oraimo": (
        "boompop", "shieldsonic", "wildcube", "hummer", "roar", "soundpro",
    ),
    "beats": (
        "studio", "solo", "pill", "flex", "fit",
    ),
    "harman": (
        "onyx", "aura",
    ),
    "havit": (
        "sk", "audiopro",
    ),
    "boat": (
        "stone", "airdopes", "rockerz",
    ),
    "boult": (
        "audio", "y1", "airbass",
    ),
}


def _find_named_family(cleaned: str, brand: str) -> str | None:
    """Match `<brand> <family> [version]` and return `family-version` (or
    just `family`) as a canonical slug fragment.

    Longest family name first so "SoundLink" beats a hypothetical "Sound".
    Version tokens covered:
      - "6", "800" → digits
      - "800MK2" → digits + trailing letters+digits
      - "Encore", "Plus", "Pro", "Max" → variant keywords
      - "" → bare family name (family alone is a real SKU)
    """
    families = BRAND_FAMILIES.get(brand, ())
    if not families:
        return None
    family_alt = "|".join(re.escape(f) for f in sorted(families, key=len, reverse=True))
    # Word boundary + family + optional whitespace + optional version.
    # The version group swallows a digit-run and any letter+digit tail
    # ("800mk2") or one of the marketing keywords. \b at the end guards
    # against greedy matches into unrelated tokens ("flip6th" wouldn't
    # match anything sensible).
    pattern = rf"\b({family_alt})\s*(\d{{1,4}}[a-z]{{0,3}}\d{{0,3}}|encore|plus|pro|max)?\b"
    m = re.search(pattern, cleaned, re.IGNORECASE)
    if not m:
        return None
    family = m.group(1).lower()
    version = (m.group(2) or "").lower()
    return f"{family}-{version}" if version else family

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
    """Pick the first model-code-shaped token that isn't the brand itself.

    Strips the brand name from `cleaned` first so "vitron v61sb" doesn't
    get captured as one long "vitronv61sb" token (which the previous regex
    was silently doing). Filters codes that are too short (< 3 chars) or
    that lack either letters or digits — those are almost always noise
    like "2.1", "5G", "IPX7".
    """
    brand_flat = brand.replace("-", "")
    # Drop the brand token(s) so it doesn't get swallowed into a code.
    stripped = re.sub(rf"\b{re.escape(brand)}\b", " ", cleaned, flags=re.IGNORECASE)
    for m in _MODEL_CODE_RE.finditer(stripped):
        code = m.group(1).lower().replace(" ", "").replace("-", "")
        if code == brand_flat:
            continue
        # Some cleaned titles retain "brandcode" as one word after the sub —
        # peel the brand prefix back off so we canonicalise on the SKU alone.
        if code.startswith(brand_flat) and len(code) > len(brand_flat):
            code = code[len(brand_flat):]
        letters = sum(1 for c in code if c.isalpha())
        digits = sum(1 for c in code if c.isdigit())
        # 3-char minimum with at least one letter AND one digit. Reject pure
        # numerics ("100W", "5000") and pure alphas.
        if len(code) < 3 or letters == 0 or digits == 0:
            continue
        # Reject single-digit codes with long letter runs — those are common
        # marketing words the regex accidentally couples to a nearby number:
        # "watts 5" → "watts5", "channel 6" → "channel6". Real short SKUs
        # (SN5, S45H) have ≤3 letters, so this heuristic is safe.
        if digits <= 1 and letters > 3:
            continue
        # If the alpha portion is a known product family for this brand,
        # defer to the named-family extractor so hyphenation stays
        # consistent ("go-4" not "go4", "flip-6" not "flip6").
        alpha_prefix = "".join(c for c in code if c.isalpha())
        if alpha_prefix in BRAND_FAMILIES.get(brand, ()):
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
        model_code = _find_model_code(cleaned, brand) or _find_named_family(cleaned, brand)
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
        model_code = _find_model_code(cleaned, brand) or _find_named_family(cleaned, brand)
        wireless = _is_wireless(cleaned)
        if model_code:
            parts.append(model_code)
            specs["model_code"] = model_code.upper()
        parts.append("wireless" if wireless else "wired")
        specs["connectivity"] = "Wireless" if wireless else "Wired"
        display_bits.append(typ.title())
        display_bits.append(specs["connectivity"])

    elif typ == "mp3-player":
        model_code = _find_model_code(cleaned, brand) or _find_named_family(cleaned, brand)
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
