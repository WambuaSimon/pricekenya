"""TV-category title parser.

Kenyan TV listings are dominated by Kenyan/regional brands (Vitron, Amtec,
Cube, Vision Plus) alongside the usual Samsung/LG/Sony/TCL/Hisense. Model
SKUs (HTC3288QS, 43S5K) exist but inconsistently, so we deliberately keep
them out of the canonical key — brand + size + resolution + panel + smart
is enough to merge listings across merchants for the same shopper-visible
product.

Non-TV items (soundbars, TV boxes, streaming sticks, wall mounts) leak into
the TV feed and are rejected outright.
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title, slugify

# Two-word brands are checked first so "Vision Plus TV" ends up as
# vision-plus, not vision.
COMPOUND_BRANDS: list[tuple[str, str]] = [
    ("vision plus", "vision-plus"),
]

KNOWN_BRANDS = {
    # Global
    "samsung", "lg", "sony", "hisense", "tcl", "skyworth", "philips", "sharp",
    "toshiba", "panasonic", "xiaomi", "changhong", "haier",
    # Kenyan / regional
    "vitron", "amtec", "cube", "lyons", "globalstar", "gld", "solarmax",
    "nobel", "ramtons", "bruhm", "syinix", "smartec", "itel", "roch",
    "starx", "digimark",
}

# Words whose presence means the listing isn't a TV. Checked as substrings.
NON_TV_MARKERS = (
    "soundbar", "sound bar",
    "tv box", "tv-box", "android box",
    "streaming stick", "chromecast", "fire stick",
    "wall mount", "wall bracket", "tv bracket",
    "remote control",
    "antenna",
    "hdmi cable", "vga cable",
    "tv stand",
    # Non-TV items that appear in some merchants' TV feeds (Hotpoint files
    # these under /catalogue/category/tvs/ but they're not TVs)
    "interactive board", "interactive display", "smartboard",
    "integrated ops", "ops pc", "opsm pc",
    "wireless dongle", "hdmi dongle", "usb dongle",
    "digital signage",
)

# Explicit "43 inch" / "43 Inch" / "43\"" / "43 INCHES" / "43-Inch"
_SIZE_RE = re.compile(r"(\d{2,3})\s*[- ]?\s*(?:\"|''|inch(?:es)?)", re.IGNORECASE)
# Fallback: bare 2-3 digit number followed by ≥1 model-code letter — Hotpoint
# writes TV titles like "Hisense 55Q6Q QLED VIDAA Smart 4K TV" and
# "LG 43UA80006LC UHD 4K Smart TV" where the size number runs into the model
# code without an inch marker.
_SIZE_MODEL_PREFIX_RE = re.compile(r"\b(\d{2,3})[a-z]+", re.IGNORECASE)

CONDITION_KEYWORDS = {
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "renewed": "refurbished",
    "used": "used",
    "brand new": "new",
}

SMART_MARKERS = (
    "smart", "android", "google tv", "webos", "tizen",
    "netflix", "youtube", "apps",
)


def _find_brand(cleaned: str) -> str | None:
    for phrase, canonical in COMPOUND_BRANDS:
        if phrase in cleaned:
            return canonical
    for tok in cleaned.split():
        # Strip trailing punctuation.
        tok = re.sub(r"[^a-z0-9-]", "", tok)
        if tok in KNOWN_BRANDS:
            return tok
    return None


def _find_size(cleaned: str) -> int | None:
    # Prefer explicit inch-marker sizes.
    for m in _SIZE_RE.finditer(cleaned):
        n = int(m.group(1))
        if 15 <= n <= 120:
            return n
    # Fallback: only fire when the title clearly claims to be a TV. Otherwise
    # a size-shaped model prefix like "43UA80006LC" would false-trigger on
    # non-TV listings.
    if not any(m in cleaned for m in (" tv", " tv,", "smart tv", "led tv", "qled tv",
                                        "oled tv", "uhd tv", "hd tv", "4k tv", "8k tv",
                                        "vidaa", "webos", "tizen", "google tv")):
        return None
    for m in _SIZE_MODEL_PREFIX_RE.finditer(cleaned):
        n = int(m.group(1))
        if 15 <= n <= 120:
            return n
    return None


def _find_resolution(cleaned: str) -> str | None:
    if "8k" in cleaned:
        return "8k"
    if "4k" in cleaned or "uhd" in cleaned:
        return "4k"
    if "full hd" in cleaned or re.search(r"\bfhd\b", cleaned):
        return "fhd"
    if re.search(r"\bhd\b", cleaned):
        return "hd"
    return None


def _find_panel(cleaned: str) -> str | None:
    """Order matters: OLED first (else 'oled' would match inside 'qoled' etc.).
    QLED before LED for the same reason."""
    if "oled" in cleaned:
        return "oled"
    if "qled" in cleaned:
        return "qled"
    if "mini led" in cleaned or "miniled" in cleaned:
        return "miniled"
    if re.search(r"\bled\b", cleaned):
        return "led"
    return None


def _is_smart(cleaned: str) -> bool:
    return any(kw in cleaned for kw in SMART_MARKERS)


def _find_condition(cleaned: str) -> str:
    for kw, cond in CONDITION_KEYWORDS.items():
        if kw in cleaned:
            return cond
    return "new"


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    # Reject non-TVs outright — soundbars and TV boxes shouldn't get into the
    # TV catalog just because the merchant filed them there.
    for marker in NON_TV_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    brand = _find_brand(cleaned)
    size = _find_size(cleaned)
    if not (brand and size):
        return ParsedTitle()

    resolution = _find_resolution(cleaned)
    panel = _find_panel(cleaned)
    smart = _is_smart(cleaned)
    condition = _find_condition(cleaned)

    # "HD" alone is used generically in Kenyan retail — every LED/QLED TV is
    # at least HD, and the word often appears as marketing filler rather than
    # a spec claim ("QLED HD Netflix TV"). We only include the resolution in
    # the canonical key when it's a real differentiator (FHD/4K/8K).
    key_resolution = resolution if resolution in ("fhd", "4k", "8k") else None

    parts = [slugify(brand), str(size)]
    if key_resolution:
        parts.append(key_resolution)
    if panel:
        parts.append(panel)
    parts.append("smart" if smart else "basic")
    if condition != "new":
        parts.append(condition)
    canonical_key = "|".join(parts)

    specs: dict = {
        "screen_inches": size,
        "smart": smart,
        "condition": condition,
    }
    if resolution:
        specs["resolution"] = resolution.upper()
    if panel:
        specs["panel_type"] = panel.upper()

    display_bits = [
        brand.replace("-", " ").title(),
        f"{size}\"",
        (specs.get("resolution") or ""),
        (specs.get("panel_type") or ""),
        ("Smart TV" if smart else "TV"),
        ("Refurbished" if condition == "refurbished" else ""),
    ]
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,  # TVs don't have a stable model line the way laptops do
        canonical_key=canonical_key,
        specs=specs,
        display_title=display,
    )
