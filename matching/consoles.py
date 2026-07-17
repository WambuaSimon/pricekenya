"""Console matcher: PlayStation 5, Xbox Series X/S, Nintendo Switch.

Three console families that share matcher shape (brand + family + optional
revision/edition/storage), so we keep them in one module with
`expected_type` dispatch — same pattern as `small_appliances.py` and
`solar_energy.py`.

Kenyan market notes:
- PS5 dominates the console category by SKU volume. Standard / Slim / Pro
  revisions coexist; Disc vs Digital edition matters for buyer intent
  (a Digital Edition can't play discs). Storage on Slim = 1TB, Pro = 2TB.
- Xbox Series X (flagship) and Series S (budget) are both stocked;
  storage keys the SKU (Series X 1TB vs 2TB).
- Nintendo Switch has four current variants: original, Lite, OLED, and
  the recent Switch 2 (~KSh 85k on Jumia).

Rejects — the console-category feed is noisy:
- Retro handheld clones (R36S, M15 Game Stick, X80, etc.) — Chinese
  imports that leak into every "gaming console" category page.
- Actual games (GTA, FC26/FIFA, Sonic, Call of Duty, etc.) — belong
  in `games-digital-cards` (matcher deferred).
- Accessories (controller, headset, dock, stand, case) — belong in
  `console-accessories`.
- Cross-family: an Xbox SKU on the PS5 leaf gets rejected so it doesn't
  collide-key onto a PS5.
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title

CONDITION_KEYWORDS: dict[str, str] = {
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "renewed": "refurbished",
    "used": "used",
    "second hand": "used",
    "brand new": "new",
}

# Family-marker phrases — used both to confirm a title belongs to the
# expected family AND (via _cross_family_reject) to reject cross-family
# listings that would otherwise pass through.
_PS5_MARKERS = ("playstation 5", "playstation®5", "play station 5", "ps5")
# Xbox family markers, ordered longest-first so Series X beats bare Xbox.
_XBOX_FAMILY_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("xbox-series-x", ("xbox series x", "series x")),
    ("xbox-series-s", ("xbox series s", "series s")),
]
# Nintendo Switch variants — order matters: Switch 2 / Lite / OLED must beat
# the bare "switch" fallback which is used only when qualified.
_SWITCH_FAMILY_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("switch-2", ("switch 2",)),
    ("switch-lite", ("switch lite",)),
    ("switch-oled", ("switch oled",)),
    ("switch", ("switch",)),
]

# PS5 revision. "Pro" first so "ps5 pro" doesn't get keyed as "slim" if
# both appear (they don't in practice, but order is defensive).
_PS5_REVISION_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("pro", ("ps5 pro", "playstation 5 pro", "playstation®5 pro")),
    ("slim", ("slim",)),
]
_PS5_EDITION_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("digital", ("digital edition", "digital version", "digital")),
    ("disc", ("disc edition", "disc version", "disc")),
]

# Storage tokens: 512GB / 825GB / 1TB / 2TB (and the rare 4TB add-on).
# The narrow set is deliberate — a random "1024" in a title shouldn't match.
_STORAGE_RE = re.compile(
    r"(?:(\d{3,4})\s*gb|(\d(?:\.\d+)?)\s*tb)\b", re.IGNORECASE
)

# Retro-handheld clones that dominate Jumia's "gaming console" search.
# Trailing space on short codes ("m15 ") prevents false positives on
# unrelated tokens (a "M158" phone won't hit "m15 ").
_RETRO_HANDHELD_MARKERS = (
    "r36s", "m15 ", "gamestick", "game stick",
    "x18 ", "x80 ", "x9 ", "j36 ",
    "linux system", "retro handheld", "retro gaming console",
    "retro classic game", "retro classic gaming",
    "handheld game console", "handheld video game",
    "mini video game", "sup game", "pxp",
    "arcade game",
    "psp",  # PSP is a legacy portable, separate family
)

# Console-accessory markers — reject from every console leaf.
_ACCESSORY_MARKERS = (
    "controller", "dualsense", "dualshock", "gamepad",
    "headset", "headphone",
    "charging dock", "charging station", "dock stand", "cooling stand",
    "carrying case", "carry bag", "hard case",
    "skin", "faceplate",
    "charging cable", "hdmi cable", "adapter", "power supply",
    "screen protector", "storage bag",
)

# Actual game titles / franchises common in Kenyan retail listings.
# These leak into console category pages because merchants shelf games
# next to consoles.
_GAME_MARKERS = (
    "fc26", "fc 26", "fc25", "fc 25", "fifa",
    "gta", "grand theft auto",
    "call of duty",
    "sonic superstars", "sonic the hedgehog",
    "spider-man", "spiderman",
    "god of war",
    "elden ring",
    "assassin",
    "mortal kombat",
    "hogwarts legacy",
    "resident evil",
    "the last of us",
    "horizon forbidden", "returnal",
    # Nintendo-specific franchises that end in "... Nintendo Switch" and
    # would otherwise trip the bare-switch family match.
    "zelda", "mario odyssey", "mario kart", "pokemon", "kirby",
    "switch sports", "animal crossing", "splatoon",
    # Digital / gift cards
    "gift card", "psn card", "psn plus", "psn subscription",
    "game pass", "xbox live", "nintendo eshop",
    # Game-bundle giveaways
    "definitive edition", "triology", "trilogy",
)


def _find_condition(cleaned: str) -> str:
    for kw, cond in CONDITION_KEYWORDS.items():
        if kw in cleaned:
            return cond
    return "new"


def _find_from_markers(
    cleaned: str, markers: list[tuple[str, tuple[str, ...]]]
) -> str | None:
    for name, phrases in markers:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _find_storage(cleaned: str) -> str | None:
    """Return storage as a normalised token like '512gb', '825gb', '1tb', '2tb'.

    Constrained to the actual console storage tiers so a random 3-digit
    number in the title doesn't misparse as storage.
    """
    for m in _STORAGE_RE.finditer(cleaned):
        gb, tb = m.group(1), m.group(2)
        if tb:
            val = float(tb)
            if val in (0.5, 1.0, 2.0, 4.0):
                token = int(val) if val == int(val) else val
                return f"{token}tb"
        elif gb:
            n = int(gb)
            if n in (256, 512, 825, 1000, 2000):
                return f"{n}gb"
    return None


def _cross_family_reject(expected: str, cleaned: str) -> bool:
    """True when the title mentions a different console family than the
    caller asked for — the row is mis-routed and should drop rather than
    collide-key onto the wrong console."""
    if expected == "ps5":
        if "xbox" in cleaned or "nintendo switch" in cleaned:
            return True
    elif expected == "xbox-series":
        if any(m in cleaned for m in _PS5_MARKERS):
            return True
        if "nintendo switch" in cleaned:
            return True
    elif expected == "switch":
        if any(m in cleaned for m in _PS5_MARKERS):
            return True
        if "xbox" in cleaned:
            return True
    return False


def parse_title(title: str, expected_type: str) -> ParsedTitle:
    if expected_type not in ("ps5", "xbox-series", "switch"):
        return ParsedTitle()

    cleaned = clean_title(title)

    # Universal rejects: retro clones, accessories, actual games. These
    # apply to all three expected_types because the same feed contains
    # the same noise regardless of which leaf routed it.
    for marker in _RETRO_HANDHELD_MARKERS + _ACCESSORY_MARKERS + _GAME_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    if _cross_family_reject(expected_type, cleaned):
        return ParsedTitle()

    condition = _find_condition(cleaned)
    specs: dict = {"condition": condition}
    parts: list[str]
    display_bits: list[str]

    if expected_type == "ps5":
        if not any(m in cleaned for m in _PS5_MARKERS):
            return ParsedTitle()
        revision = _find_from_markers(cleaned, _PS5_REVISION_MARKERS) or "standard"
        edition = _find_from_markers(cleaned, _PS5_EDITION_MARKERS)
        storage = _find_storage(cleaned)
        parts = ["sony", "ps5", revision]
        specs["revision"] = revision.title()
        display_bits = ["Sony", "PlayStation 5"]
        if revision != "standard":
            display_bits.append(revision.title())
        if edition:
            parts.append(edition)
            specs["edition"] = edition.title()
            display_bits.append(f"{edition.title()} Edition")
        if storage:
            parts.append(storage)
            specs["storage"] = storage.upper()
            display_bits.append(storage.upper())
        brand = "sony"

    elif expected_type == "xbox-series":
        family = _find_from_markers(cleaned, _XBOX_FAMILY_MARKERS)
        if not family:
            return ParsedTitle()
        storage = _find_storage(cleaned)
        parts = ["microsoft", family]
        specs["family"] = family.replace("-", " ").title()
        display_bits = ["Microsoft", family.replace("-", " ").title()]
        if storage:
            parts.append(storage)
            specs["storage"] = storage.upper()
            display_bits.append(storage.upper())
        brand = "microsoft"

    else:  # switch
        family = _find_from_markers(cleaned, _SWITCH_FAMILY_MARKERS)
        if not family:
            return ParsedTitle()
        # Bare "switch" is ambiguous — network switches, KVM switches, and
        # Switch GAMES (e.g. "Zelda Nintendo Switch") all contain the token.
        # A real console listing almost always spells out "console" or names
        # the included Joy-Cons; game titles don't. Require one of those
        # signals when the family match is the bare "switch" fallback. The
        # qualified variants (switch 2 / lite / oled) are self-identifying.
        if family == "switch":
            if not any(m in cleaned for m in ("console", "joy-con", "joycon")):
                return ParsedTitle()
        parts = ["nintendo", family]
        specs["family"] = family.replace("-", " ").title()
        display_bits = ["Nintendo", family.replace("-", " ").title()]
        brand = "nintendo"

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
