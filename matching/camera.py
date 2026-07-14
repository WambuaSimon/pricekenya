"""Camera matcher.

The Kenyan online camera market is dominated by cheap Chinese imports:
security/IP cameras, body cams, action cams, and generic "digital cameras".
Real branded DSLRs and mirrorless bodies are rare. This matcher:

1. Rejects accessories aggressively (tripods, microphones, camera bags,
   flash mounts, lens filters, memory cards) — Kilimall's ?q=dslr search
   returns almost entirely accessories, and Jumia's /cameras/ mixes them in
   too.
2. Detects device type from title keywords (dslr / mirrorless / action /
   security / body / instant / drone / kids / digital).
3. Includes a model code (RX200, DC226, LK003, ZC-M6) in the canonical key
   when present — generic Chinese imports repeat the same model code across
   merchants, which is the only reliable merge signal.
4. Falls back to megapixels + resolution when no brand OR model code exists,
   but only for well-identified types (action-cam / kids-camera / security).
"""

from __future__ import annotations

import re

from matching.appliance_base import find_condition
from matching.base import ParsedTitle, clean_title, slugify

KNOWN_BRANDS = {
    # Traditional camera brands (rare on Kenyan retail)
    "canon", "nikon", "sony", "fujifilm", "fuji", "olympus", "panasonic",
    "leica", "pentax", "kodak", "polaroid",
    # Action / adventure
    "gopro", "insta360", "dji",
    # Security-cam brands common in Kenya
    "hikvision", "dahua", "tp-link", "xiaomi", "eufy", "reolink",
    "ezviz", "imilab", "yi", "wyze",
    # Chinese generic-camera brands that appear on Jumia / Kilimall
    "v380", "vic", "addigoes", "2nlf", "lasa",
    # Consumer electronics brands that also sell cameras
    "samsung", "hisense", "vitron", "amtec", "havit",
}

TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("action-cam", ("action camera", "action cam", "sports camera", "gopro",
                    "body camera", "body cam", "police cam", "vlog recorder")),
    ("security-cam", ("security camera", "cctv", "ip camera", "surveillance",
                      "bulb camera", "outdoor camera", "wifi camera",
                      "dome camera", "ptz camera", "spy camera", "hidden camera",
                      "mini camera")),
    ("instant-camera", ("instant camera", "instant printing", "polaroid camera")),
    ("drone-camera", ("drone camera", "aerial camera", "rc drone")),
    ("kids-camera", ("kids camera", "student camera", "children camera")),
    ("mirrorless", ("mirrorless",)),
    ("dslr", ("dslr camera", " dslr", "dslr ", "slr camera")),
    ("digital-camera", ("digital camera", "video camera", "camcorder",
                        "vlog camera", "vlogging camera", "digital video")),
]

# Accessory rejection — these words indicate the listing is NOT a camera.
NON_CAMERA_MARKERS = (
    "tripod", "monopod", "gimbal stand",
    "camera bag", "camera backpack", "photography backpack", "shoulder bag",
    "camera case", "hard case",
    "microphone", "lavalier", "lapel mic", "lav mic", "wireless mic",
    "hot shoe", "flash mount", "cold shoe", "shoe adapter",
    "camera stand", "camera flash", "ring light",
    "memory card", "sd card", "cf card", "card reader",
    "lens filter", "lens cap", "lens hood", "lens adapter",
    "camera strap", "camera charger", "battery grip", "battery pack",
    "phone holder", "clip mount", "selfie stick",
    "cable release", "shutter release",
    "usb cable only", "hdmi cable",
    "screen protector",
    # Camera mounts / holders / adapters — the "Camera Suction Cup Mount"
    # class of listing sneaks in because the title contains "action camera"
    # phrase-for-phrase.
    "camera mount", "camera holder", "camera adapter", "camera bracket",
    "suction cup mount", "action camera holder", "action camera mount",
    "action camera adapter", "action camera bracket",
    "helmet mount", "handlebar mount", "chest mount", "head mount",
    "windshield mount", "car mount", "bike mount", "wrist mount",
)

# Megapixels: "64MP", "48 MP", "88 Million Pixel"
_MP_RE = re.compile(r"(\d{1,3})\s*(?:mp|megapixel|million\s*pixel)", re.IGNORECASE)
# Zoom: "18X", "28X Zoom", "16X Digital Zoom"
_ZOOM_RE = re.compile(r"(\d{1,3})\s*x\s*(?:zoom|optical|digital)", re.IGNORECASE)
# Resolution
_RES_4K_RE = re.compile(r"\b4k\b|\bultra\s*hd\b", re.IGNORECASE)
_RES_8K_RE = re.compile(r"\b8k\b", re.IGNORECASE)
_RES_6K_RE = re.compile(r"\b6k\b", re.IGNORECASE)
_RES_1080P_RE = re.compile(r"\b1080p\b|\bfull\s*hd\b", re.IGNORECASE)
_RES_720P_RE = re.compile(r"\b720p\b", re.IGNORECASE)

# Model code — same regex family as the audio matcher but tuned for camera SKUs.
# Accept slightly shorter alnum runs since camera codes like "DC226" or "RX200"
# are common (2 letters + 3 digits).
_MODEL_CODE_RE = re.compile(r"\b([a-z]{1,4}[- ]?\d{2,5}[a-z]?)\b", re.IGNORECASE)

# GoPro's "Hero N" family is THE model identifier for action cams in Kenya,
# but the letter-count and digit-count don't fit _MODEL_CODE_RE (Hero has
# 4 letters and Hero versions are 1-2 digits vs the general regex's 2-5
# digit floor). Match this family explicitly so GoPro Hero 8 doesn't
# collapse with Hero 13.
# Two patterns tried in order:
#   1. hero adjacent to digits ("HERO10", "Hero 13", "hero 8")
#   2. hero with up to ~20 chars gap ("Hero Gopro 11" — Jumia word order)
_GOPRO_HERO_RE = re.compile(r"\bhero\s*(\d{1,2})\b", re.IGNORECASE)
_GOPRO_HERO_LOOSE_RE = re.compile(r"\bhero\b.{1,20}?\b(\d{1,2})\b", re.IGNORECASE)
# GoPro Max (360-degree camera). Just the word "max" plus optional 360.
_GOPRO_MAX_RE = re.compile(r"\bmax\b(\s*360)?", re.IGNORECASE)
# DJI's Osmo family — same structural exception.
_DJI_OSMO_RE = re.compile(
    r"\bosmo\s+(action\s*\d|pocket\s*\d?|mobile\s*\d)\b", re.IGNORECASE
)
# Insta360 families: One RS/R/X3/X4, X-series direct (X3, X4).
_INSTA_ONE_RE = re.compile(r"\bone\s+([a-z]{1,3}\d?)\b", re.IGNORECASE)
_INSTA_X_RE = re.compile(r"\b(x\d)\b", re.IGNORECASE)

# Brands whose entire consumer camera lineup is action cams. If we detected
# the brand but the "action camera" marker phrase isn't in the title
# verbatim, default type to action-cam rather than dropping the listing.
_ACTION_CAM_BRANDS = frozenset({"gopro", "dji", "insta360"})

# Words that model_code should skip (they match the regex but aren't SKUs).
_MODEL_CODE_BLOCKLIST = {
    # Version + spec noise
    "wifi", "bluetooth", "bt", "hd", "fhd", "uhd", "led", "lcd",
    "4k", "8k", "6k", "2k", "720p", "1080p", "pro",
    # Common colors / sizes
    "black", "white", "blue", "red",
    # Random measurements
    "cm", "mm", "km",
    # Brand tokens (we skip the brand's own token anyway, but as a safety)
    "canon", "nikon", "sony",
}
# Numeric fragments that indicate the "model code" candidate is actually a
# resolution claim (e.g. "pro1080p" -> digits 1080). Reject these.
_RESOLUTION_NUMBERS = {"1080", "720", "480", "360", "240", "4320"}


def _find_brand(cleaned: str) -> str | None:
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


def _find_megapixels(cleaned: str) -> int | None:
    for m in _MP_RE.finditer(cleaned):
        n = int(m.group(1))
        # Kenyan retail wildly overstates MP (68MP, 88MP, 500MP marketing) but
        # real sensor MP tops out around 100 for pro DSLRs. Cap generously.
        if 1 <= n <= 200:
            return n
    return None


def _find_zoom(cleaned: str) -> int | None:
    for m in _ZOOM_RE.finditer(cleaned):
        n = int(m.group(1))
        if 2 <= n <= 200:
            return n
    return None


def _find_resolution(cleaned: str) -> str | None:
    """Return the highest resolution mentioned in the title."""
    if _RES_8K_RE.search(cleaned):
        return "8k"
    if _RES_6K_RE.search(cleaned):
        return "6k"
    if _RES_4K_RE.search(cleaned):
        return "4k"
    if _RES_1080P_RE.search(cleaned):
        return "1080p"
    if _RES_720P_RE.search(cleaned):
        return "720p"
    return None


def _find_model_code(cleaned: str, brand: str | None) -> str | None:
    """Pick the first non-noise model code that isn't the brand itself."""
    # Brand-family exceptions first — these families use short model codes
    # that don't fit the general model_code regex (Hero 8, Osmo Action, etc.).
    if brand == "gopro":
        # Hero family (versions 1-14 as of 2026).
        m = _GOPRO_HERO_RE.search(cleaned) or _GOPRO_HERO_LOOSE_RE.search(cleaned)
        if m:
            return f"hero{m.group(1)}"
        # Max is GoPro's 360-degree camera.
        if _GOPRO_MAX_RE.search(cleaned):
            return "max"
    if brand == "dji":
        m = _DJI_OSMO_RE.search(cleaned)
        if m:
            return "osmo-" + m.group(1).replace(" ", "").lower()
    if brand == "insta360":
        m = _INSTA_ONE_RE.search(cleaned)
        if m:
            return "one-" + m.group(1).lower()
        m = _INSTA_X_RE.search(cleaned)
        if m:
            return m.group(1).lower()

    brand_flat = (brand or "").replace("-", "")
    for m in _MODEL_CODE_RE.finditer(cleaned):
        code_raw = m.group(1).lower()
        code = code_raw.replace(" ", "").replace("-", "")
        if code == brand_flat:
            continue
        if code in _MODEL_CODE_BLOCKLIST:
            continue
        letters = sum(1 for c in code if c.isalpha())
        digits = sum(1 for c in code if c.isdigit())
        # Camera SKUs range from V380 (1 letter + 3 digits) to LK003, DC226,
        # RX200 (2 letters + 3 digits). Total length ≥ 4 rules out short
        # spec tokens like "4K" or "5G".
        if letters < 1 or digits < 3 or (letters + digits) < 4:
            continue
        # Reject candidates whose digit run is a resolution number (1080,
        # 720, etc.) — the letters are usually qualifiers like "Pro" or "HD"
        # attached to a resolution claim, not a real SKU.
        digit_run = "".join(c for c in code if c.isdigit())
        if digit_run in _RESOLUTION_NUMBERS:
            continue
        return code
    return None


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)

    for marker in NON_CAMERA_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    brand = _find_brand(cleaned)
    typ = _find_type(cleaned)
    # For brands whose entire consumer camera lineup is action-cams
    # (GoPro, DJI's Osmo Action line, Insta360), default to action-cam
    # when the type-marker phrase isn't in the title verbatim. Otherwise
    # a "DJI Osmo Action 4 Standard Combo" gets rejected simply because
    # it doesn't literally say "action camera".
    if not typ and brand in _ACTION_CAM_BRANDS:
        typ = "action-cam"
    if not typ:
        return ParsedTitle()

    model_code = _find_model_code(cleaned, brand)
    megapixels = _find_megapixels(cleaned)
    zoom = _find_zoom(cleaned)
    resolution = _find_resolution(cleaned)
    condition = find_condition(cleaned)

    # Need at least one identifier beyond the raw type — brand, model code,
    # a resolution claim (4K/1080p/etc.), OR a megapixel spec. Generic camera
    # listings that have none of these are anonymous enough that indexing
    # them just clutters the catalog.
    has_identifier = bool(brand or model_code or resolution or megapixels)
    if not has_identifier:
        return ParsedTitle()

    brand_slug = slugify(brand) if brand else "generic"
    parts = [brand_slug, typ]
    if model_code:
        parts.append(model_code)
    else:
        if resolution:
            parts.append(resolution)
        if megapixels:
            parts.append(f"{megapixels}mp")

    if condition != "new":
        parts.append(condition)

    canonical_key = "|".join(parts)

    specs: dict = {"type": typ.replace("-", " ").title(), "condition": condition}
    if model_code:
        specs["model_code"] = model_code.upper()
    if megapixels:
        specs["megapixels"] = megapixels
    if zoom:
        specs["zoom"] = f"{zoom}X"
    if resolution:
        specs["resolution"] = resolution.upper()

    display_bits = [
        (brand.replace("-", " ").title() if brand else "Generic"),
        typ.replace("-", " ").title(),
    ]
    if model_code:
        display_bits.append(model_code.upper())
    if resolution:
        display_bits.append(resolution.upper())
    if megapixels:
        display_bits.append(f"{megapixels}MP")
    if condition != "new":
        display_bits.append(condition.title())
    display = " ".join(display_bits).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key=canonical_key,
        specs=specs,
        display_title=display,
    )
