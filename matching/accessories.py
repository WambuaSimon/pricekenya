"""Accessories matcher: phone/tablet/computing/gaming accessories.

Merchants throw a lot of shapes into their accessory feeds — chargers,
cables, power banks, cases, screen protectors, styluses, smartwatches,
earbuds, controllers, keyboards, mice — under a small number of leaf
categories. Rather than one file per leaf we consolidate here and
dispatch on the detected type.

Each PriceKenya accessory leaf specifies which types belong in it, so a
gaming controller that leaks into `phone-tablet-accessories` gets
rejected and a wall charger that leaks into `console-accessories`
likewise. This mirrors the expected-type gate in small_appliances.py.

Merging strategy: require brand + type + at least one distinguishing
spec (wattage / mAh / connector pair / model line). Without those we
can't safely merge two "silicone case" listings across merchants —
they're likely different products — so we drop the row. Coverage
worse-than-perfect is better than fragmented price data.
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title, slugify

# --------------------------------------------------------------------------
# Brand list
# --------------------------------------------------------------------------
# Sourced from actual Phone Place + Phones Store accessory catalogues plus
# the brands that dominate the Kenyan accessory retail scene. Compound-word
# brands are checked first as phrases in the cleaned title (e.g. "l avvento"
# beats a token-by-token scan that would only find "l").
ACCESSORY_COMPOUND_BRANDS: list[tuple[str, str]] = [
    ("l'avvento", "lavvento"),
    ("l avvento", "lavvento"),
    ("green lion", "greenlion"),
    ("green cell", "greencell"),
    ("black shark", "blackshark"),
    ("apple watch", "apple"),  # normalise "Apple Watch Series 10" → brand=apple
    ("apple pencil", "apple"),
]

ACCESSORY_BRANDS: set[str] = {
    # Phone / tablet OEMs
    "apple", "samsung", "google", "xiaomi", "redmi", "huawei", "honor",
    "oppo", "vivo", "realme", "oneplus", "tecno", "infinix", "itel", "nokia",
    # Charging + cable specialists (dominant on Kenyan sites)
    "anker", "baseus", "ugreen", "belkin", "aukey", "ravpower", "romoss",
    "oraimo", "riversong", "portronics", "lavvento", "sonicgear",
    "borofone", "hoco", "remax", "xo", "usams", "yesido", "wiwu",
    "greenlion", "greencell",
    # Case brands
    "spigen", "otterbox", "esr", "uag", "caseology", "ringke",
    # Audio / earbud brands
    "sony", "bose", "jbl", "sennheiser", "beats", "skullcandy",
    "edifier", "philips",
    # Gaming
    "microsoft", "nintendo", "razer", "steelseries", "hyperx",
    "corsair", "fantech", "redragon", "havit", "blackshark",
    "8bitdo",
    # Peripherals
    "logitech", "hp", "lenovo", "dell", "asus", "genius",
    "zebronics", "iball",
}

# --------------------------------------------------------------------------
# Type detection
# --------------------------------------------------------------------------
# Order matters: named product-lines that carry brand identity (AirPods,
# Apple Watch, MagSafe, DualSense…) are checked before generic form-factor
# words (case, cover, headset) so "AirPods Pro 2 with USB-C Case" types as
# earbuds, not "case". Generic form-factors go last so they only win when
# nothing more specific matched.
TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    # Named product-lines with brand identity
    ("earbuds", ("airpods", "true wireless earbuds", "wireless earbuds",
                 "tws earbuds")),
    ("smartwatch", ("apple watch", "galaxy watch", "watch series",
                    "smartwatch", "smart watch")),
    ("stylus", ("apple pencil", "s pen", "stylus pen", "stylus")),
    ("wireless-charger", ("magsafe charger", "wireless charger",
                          "wireless charging pad", "qi charger")),
    # Charging / cable form factors
    ("power-bank", ("power bank", "powerbank", "power-bank", "portable charger")),
    ("car-charger", ("car charger", "car adapter", "car mount charger")),
    ("charger", ("wall charger", "power adapter", "fast charger",
                 "usb charger", "charging adapter", "gan charger", "charger",
                 "power brick", "adapter")),
    ("cable", ("charging cable", "usb cable", "lightning cable", "usb-c cable",
               "type-c cable", "type c cable", "micro-usb cable", "cable",
               "cord")),
    # Gaming / console
    ("controller", ("dualsense", "dualshock", "xbox controller",
                    "gaming controller", "controller", "gamepad", "joystick")),
    ("gaming-headset", ("gaming headset", "gaming headphone")),
    ("charging-dock", ("charging dock", "charging station", "docking station")),
    # Computing peripherals
    ("keyboard", ("gaming keyboard", "mechanical keyboard", "wireless keyboard",
                  "keyboard")),
    ("mouse", ("gaming mouse", "wireless mouse", "mouse")),
    ("headset", ("headset", "headphones", "headphone")),
    ("usb-hub", ("usb hub", "usb-c hub", "docking hub")),
    ("webcam", ("webcam", "web camera")),
    # Generic form-factor words last — they'd otherwise steal specific matches
    ("earbuds", ("earbuds",)),
    ("screen-protector", ("screen protector", "tempered glass", "hydrogel",
                          "screen guard", "screen film")),
    ("case", ("phone case", "phone cover", "silicone case", "leather case",
              "flip cover", "back cover", "case", "cover")),
]

# Types allowed per PriceKenya leaf. Anything scraped into a leaf whose type
# isn't in this set gets rejected (kept mistakes off the category page).
CATEGORY_ACCEPTED_TYPES: dict[str, frozenset[str]] = {
    "phone-tablet-accessories": frozenset({
        "power-bank", "wireless-charger", "car-charger", "charger", "cable",
        "screen-protector", "case", "earbuds", "smartwatch", "stylus",
    }),
    "peripherals-accessories": frozenset({
        "keyboard", "mouse", "usb-hub", "webcam", "headset", "cable",
        "charger",  # laptop chargers live here too
    }),
    "console-accessories": frozenset({
        "controller", "gaming-headset", "charging-dock", "headset",
    }),
}

# Titles that mention the type keyword but aren't the product itself. Keeps
# accessory-of-accessory items (case for a charger, stand for a phone) out.
NON_MATCHES: tuple[str, ...] = (
    "spare part", "replacement", "repair kit",
    "case for airpods", "case for buds", "airpods case",  # case around AirPods, not phone
    "cable organizer", "cable clip", "cable tie", "cable holder",
    "phone stand", "phone holder", "phone grip", "pop socket", "popsocket",
    "ring holder", "car mount",  # generic mounts without charging
    "headphone stand", "headset stand",
    "keyboard cover", "keyboard skin",
    "mouse pad", "mousepad",
)

# --------------------------------------------------------------------------
# Spec extractors
# --------------------------------------------------------------------------
_WATTS_RE = re.compile(r"(\d{1,3})\s*w\b", re.IGNORECASE)
_MAH_RE = re.compile(r"(\d{3,6})\s*mah", re.IGNORECASE)
_MODEL_NUM_RE = re.compile(r"\b([a-z]{1,3}\d{2,5}[a-z]?)\b", re.IGNORECASE)
_APPLE_PENCIL_GEN_RE = re.compile(
    r"apple pencil\s*(?:\(?(\d)(?:st|nd|rd|th)?\s*gen(?:eration)?\)?|pro|usb-c)?",
    re.IGNORECASE,
)
_APPLE_WATCH_SERIES_RE = re.compile(
    r"apple watch\s*(?:series\s*(\d+)|(se|ultra\s*\d*|ultra))",
    re.IGNORECASE,
)
_SAMSUNG_WATCH_RE = re.compile(
    r"galaxy watch\s*(\d+|active\s*\d*|ultra|fe)",
    re.IGNORECASE,
)

# Named-product variants for gaming gear. Controller/headset SKUs like
# CFI-ZCT1W or KHX-HSCP-RD don't fit the [a-z]{1,3}\d{2,5} pattern so we
# recognize the product line by name instead — that's how shoppers search
# anyway ("DualSense", "Cloud II"), not by SKU.
CONTROLLER_VARIANTS: list[tuple[str, str]] = [
    ("dualsense edge", "dualsense-edge"),
    ("dualsense", "dualsense"),
    ("dualshock 4", "dualshock-4"),
    ("dualshock", "dualshock"),
    ("xbox elite series 2", "xbox-elite-2"),
    ("xbox elite", "xbox-elite"),
    ("xbox series x", "xbox-series-x"),
    ("xbox wireless", "xbox-wireless"),
    ("pro controller", "switch-pro"),
    ("joy-con", "joycon"),
]

GAMING_HEADSET_VARIANTS: list[tuple[str, str]] = [
    ("cloud alpha", "cloud-alpha"),
    ("cloud stinger", "cloud-stinger"),
    ("cloud iii", "cloud-3"),
    ("cloud ii", "cloud-2"),
    ("barracuda", "barracuda"),
    ("kraken", "kraken"),
    ("blackshark v2", "blackshark-v2"),
    ("blackshark", "blackshark"),
    ("arctis nova", "arctis-nova"),
    ("arctis", "arctis"),
]

# Cable connector detection. Order matters — "usb-c to lightning" must beat
# a naive "usb-c" first match.
_CABLE_CONNECTOR_PAIRS: list[tuple[str, tuple[str, ...]]] = [
    ("usbc-lightning", ("usb-c to lightning", "usbc to lightning",
                        "type-c to lightning", "type c to lightning")),
    ("usba-lightning", ("usb-a to lightning", "usba to lightning",
                        "usb to lightning", "lightning cable")),
    ("usbc-usbc", ("usb-c to usb-c", "usbc to usbc", "type-c to type-c",
                   "type c to type c")),
    ("usba-usbc", ("usb-a to usb-c", "usba to usbc", "usb to usb-c",
                   "usb to type-c", "type-c cable", "usb-c cable")),
    ("usba-microusb", ("usb-a to micro-usb", "usb to micro-usb",
                       "micro-usb cable", "micro usb cable")),
]


def _find_type(cleaned: str) -> str | None:
    for name, phrases in TYPE_MARKERS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_brand(cleaned: str) -> str | None:
    for phrase, canonical in ACCESSORY_COMPOUND_BRANDS:
        if phrase in cleaned:
            return canonical
    for tok in cleaned.split():
        stripped = re.sub(r"[^a-z0-9]", "", tok)
        if stripped in ACCESSORY_BRANDS:
            return stripped
    return None


def _find_watts(cleaned: str) -> int | None:
    for m in _WATTS_RE.finditer(cleaned):
        n = int(m.group(1))
        if 5 <= n <= 240:
            return n
    return None


def _find_mah(cleaned: str) -> int | None:
    for m in _MAH_RE.finditer(cleaned):
        n = int(m.group(1))
        if 1000 <= n <= 50000:
            return n
    return None


def _find_cable_connectors(cleaned: str) -> str | None:
    for name, phrases in _CABLE_CONNECTOR_PAIRS:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_named_variant(cleaned: str, variants: list[tuple[str, str]]) -> str | None:
    for phrase, canonical in variants:
        if phrase in cleaned:
            return canonical
    return None


def _find_apple_watch_variant(cleaned: str) -> str | None:
    m = _APPLE_WATCH_SERIES_RE.search(cleaned)
    if not m:
        return None
    if m.group(1):
        return f"series-{m.group(1)}"
    variant = m.group(2).lower().replace(" ", "-")
    return variant


def _find_samsung_watch_variant(cleaned: str) -> str | None:
    m = _SAMSUNG_WATCH_RE.search(cleaned)
    if not m:
        return None
    return m.group(1).lower().replace(" ", "-")


def _find_apple_pencil_gen(cleaned: str) -> str | None:
    if "apple pencil" not in cleaned:
        return None
    if "pro" in cleaned.split("apple pencil", 1)[1][:20]:
        return "pro"
    if "usb-c" in cleaned or "usb c" in cleaned:
        return "usb-c"
    m = _APPLE_PENCIL_GEN_RE.search(cleaned)
    if m and m.group(1):
        return f"{m.group(1)}gen"
    return None


def _find_model_number(cleaned: str) -> str | None:
    """Best-effort model line for accessories that carry a model code
    (e.g. Anker A2321, Baseus PPBLD30). Kept conservative — matches
    an alphanumeric token with 1-3 letters + 2-5 digits."""
    for m in _MODEL_NUM_RE.finditer(cleaned):
        candidate = m.group(1).lower()
        # Skip pure-year-looking or wattage-looking noise
        if candidate.isdigit():
            continue
        return candidate
    return None


# --------------------------------------------------------------------------
# Main entrypoint
# --------------------------------------------------------------------------
def parse_title(title: str, expected_category: str) -> ParsedTitle:
    accepted = CATEGORY_ACCEPTED_TYPES.get(expected_category)
    if not accepted:
        return ParsedTitle()

    cleaned = clean_title(title)

    for marker in NON_MATCHES:
        if marker in cleaned:
            return ParsedTitle()

    detected = _find_type(cleaned)
    if not detected or detected not in accepted:
        return ParsedTitle()

    brand = _find_brand(cleaned)
    if not brand:
        # No brand — nothing safe to merge on. Drop.
        return ParsedTitle()

    specs: dict = {"type": detected.replace("-", " ").title()}
    parts = [slugify(brand), detected]
    display_bits = [brand.replace("-", " ").title()]

    if detected == "power-bank":
        mah = _find_mah(cleaned)
        watts = _find_watts(cleaned)
        if not mah:
            return ParsedTitle()  # capacity is the identifying signal
        parts.append(f"{mah}mah")
        specs["capacity_mah"] = mah
        display_bits.append(f"{mah}mAh Power Bank")
        if watts:
            specs["watts"] = watts
            display_bits.append(f"({watts}W)")

    elif detected in ("charger", "wireless-charger", "car-charger"):
        watts = _find_watts(cleaned)
        model = _find_model_number(cleaned)
        if not (watts or model):
            return ParsedTitle()  # need one distinguishing spec
        if model:
            parts.append(slugify(model))
            specs["model"] = model.upper()
        if watts:
            parts.append(f"{watts}w")
            specs["watts"] = watts
        pretty_type = detected.replace("-", " ").title()
        display_bits.append(pretty_type)
        if watts:
            display_bits.append(f"({watts}W)")
        if model:
            display_bits.append(model.upper())

    elif detected == "cable":
        connectors = _find_cable_connectors(cleaned)
        if not connectors:
            return ParsedTitle()  # generic "cable" without connector info is unmergeable
        parts.append(connectors)
        specs["connectors"] = connectors.replace("-", " → ").upper()
        display_bits.append(f"{connectors.upper().replace('-', ' → ')} Cable")

    elif detected == "smartwatch":
        if brand == "apple":
            variant = _find_apple_watch_variant(cleaned)
            if not variant:
                return ParsedTitle()
            parts.append(variant)
            specs["variant"] = variant.replace("-", " ").title()
            display_bits.append(f"Watch {variant.replace('-', ' ').title()}")
        elif brand == "samsung":
            variant = _find_samsung_watch_variant(cleaned)
            if not variant:
                return ParsedTitle()
            parts.append(variant)
            specs["variant"] = f"Galaxy Watch {variant.title()}"
            display_bits.append(f"Galaxy Watch {variant.title()}")
        else:
            model = _find_model_number(cleaned)
            if not model:
                return ParsedTitle()
            parts.append(slugify(model))
            specs["model"] = model.upper()
            display_bits.append(f"Smartwatch {model.upper()}")

    elif detected == "stylus":
        if brand == "apple":
            gen = _find_apple_pencil_gen(cleaned)
            if not gen:
                return ParsedTitle()
            parts.append(gen)
            specs["generation"] = gen.replace("-", " ").title()
            display_bits.append(f"Pencil ({gen.replace('-', ' ').title()})")
        elif brand == "samsung":
            display_bits.append("S Pen")
            # No further specs required — S Pen is model-specific but merchants
            # rarely tag the target Galaxy model in the title.
        else:
            model = _find_model_number(cleaned)
            if not model:
                return ParsedTitle()
            parts.append(slugify(model))
            specs["model"] = model.upper()
            display_bits.append(f"Stylus {model.upper()}")

    elif detected == "earbuds":
        model = _find_model_number(cleaned)
        # AirPods Pro / AirPods Max are named products, not model numbers
        for named in ("airpods max", "airpods pro 2", "airpods pro",
                      "airpods 4", "airpods 3", "airpods 2"):
            if named in cleaned:
                model = named.replace(" ", "-")
                break
        if not model:
            return ParsedTitle()
        parts.append(slugify(model))
        specs["model"] = model.replace("-", " ").title()
        display_bits.append(model.replace("-", " ").title())

    elif detected == "controller":
        variant = _find_named_variant(cleaned, CONTROLLER_VARIANTS)
        model = variant or _find_model_number(cleaned)
        if not model:
            return ParsedTitle()
        parts.append(slugify(model))
        specs["model"] = model.replace("-", " ").title() if variant else model.upper()
        display_bits.append(specs["model"] + " Controller")

    elif detected == "gaming-headset":
        variant = _find_named_variant(cleaned, GAMING_HEADSET_VARIANTS)
        model = variant or _find_model_number(cleaned)
        if not model:
            return ParsedTitle()
        parts.append(slugify(model))
        specs["model"] = model.replace("-", " ").title() if variant else model.upper()
        display_bits.append(specs["model"] + " Headset")

    elif detected in ("headset", "keyboard", "mouse", "webcam", "usb-hub",
                      "charging-dock", "screen-protector", "case"):
        model = _find_model_number(cleaned)
        if not model:
            return ParsedTitle()  # need a model line to distinguish across merchants
        parts.append(slugify(model))
        specs["model"] = model.upper()
        pretty_type = detected.replace("-", " ").title()
        display_bits.append(f"{pretty_type} {model.upper()}")

    canonical_key = "|".join(parts)
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=specs.get("model") if isinstance(specs.get("model"), str) else None,
        canonical_key=canonical_key,
        specs=specs,
        display_title=display,
    )
