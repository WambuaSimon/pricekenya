"""Phone-category title parser.

Turns titles like:
  "Tecno Spark 30C 5G - 8GB+256GB - Black"
  "Tecno Spark 30 C (256+8) - Magic Skin Black"
into the same canonical key:
  "tecno|spark-30c|256|8"

Anything ambiguous (no brand found, no model found) returns an unparsed
ParsedTitle. Those get skipped by the ingest pipeline; v1 will queue them for
LLM disambiguation.
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title, slugify

KNOWN_BRANDS = {
    "tecno",
    "infinix",
    "samsung",
    "xiaomi",
    "redmi",
    "poco",
    "oppo",
    "vivo",
    "realme",
    "huawei",
    "honor",
    "apple",
    "iphone",
    "nokia",
    "itel",
    "oneplus",
    "google",
    "pixel",
}

# Sub-brands / marketing names that map to a parent brand for canonicalization.
BRAND_ALIASES = {
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "iphone": "apple",
    "pixel": "google",
}

# Words that pad the title but don't identify the product. Stripped before model extraction.
NOISE_TOKENS = {"galaxy", "smartphone", "phone", "5g", "4g", "lte", "dual", "sim"}

# Titles whose primary product is a phone-adjacent ACCESSORY, not a phone.
# Leading/trailing spaces where needed to avoid matching mid-word substrings
# ("case" would otherwise match "showcase" or "encased"; " case" only matches
# when the word is a standalone token). Kept in one place so the LLM prompt
# and the retroactive normalization script can reference the same rules.
NON_PHONE_MARKERS: tuple[str, ...] = (
    # Cases / covers
    " case", "phone case", "silicone case", "leather case", "wallet case",
    "clear case", "protective case", "flip case", "hard case",
    " cover", "phone cover", "back cover", "flip cover",
    # Protection film / glass
    "screen protector", "screen guard", "tempered glass", "hydrogel",
    "privacy film", "protective film", "phone skin", "vinyl skin",
    "skin sticker",
    # Chargers / cables / power
    " charger", "phone charger", "wall charger", "car charger",
    "wireless charger", "magsafe charger", "fast charger", "gan charger",
    " adapter", "power adapter", "usb adapter",
    " cable", "charging cable", "lightning cable", "type-c cable",
    "micro-usb cable", " cord",
    "power bank", "powerbank",
    # Mounts / holders / stands
    "phone holder", "phone stand", "phone grip", "pop socket", "popsocket",
    "ring holder", "car mount", " mount", "phone mount",
    # Audio accessories that get filed under phones
    "airpods", "earbuds", "earphones", "headphones", "headset",
    # Watch accessories — using bare " strap" / " band" catches "Watch 6
    # Strap" as well as "Watch Strap". No real phone title contains these
    # tokens as standalone words.
    "watch band", "watch strap", "watch case", "watch cover",
    " strap", " band ", "wrist strap",
    # Repair / spare parts
    "spare part", "replacement", "back glass replacement",
    "battery replacement", "screen replacement", "lcd replacement",
    "camera lens protector", "lens protector",
    # Selfie / photography accessories
    "selfie stick", "phone tripod", "gimbal", "phone ring light",
    # Stylus / pens
    "stylus pen", "s pen only",
    # Bags / pouches
    "phone pouch", "phone sleeve",
)


def _is_phone_accessory(cleaned: str) -> bool:
    """True when the title's primary product is an accessory, not the phone.

    The check is a phrase-substring match on the pre-lowercased title. Order
    within NON_PHONE_MARKERS is not significant; every listed phrase is a
    veto if present.
    """
    return any(marker in cleaned for marker in NON_PHONE_MARKERS)

# "8GB+256GB", "8/256", "8 + 256", etc. — high-confidence storage pair.
# The leading (?<!\.) rejects matches like "2.0+12" (from "Battery 2.0+12 MONTHS WARRANTY")
# where the "0" would otherwise be captured as RAM.
_STORAGE_PAIR_RE = re.compile(
    r"(?<!\.)(?P<a>\d{1,3})\s*(?:gb)?\s*[+/]\s*(?P<b>\d{2,4})\s*(?:gb)?",
    re.IGNORECASE,
)
_STORAGE_MIN_GB, _STORAGE_MAX_GB = 16, 4096
_RAM_MIN_GB, _RAM_MAX_GB = 2, 32
_ALL_GB_RE = re.compile(r"(\d{1,4})\s*gb", re.IGNORECASE)
# Model + optional variant suffix. Variant alternation is ORDER-SENSITIVE:
# longer phrases come first so `pro max` matches whole before `pro` swallows
# just the "pro". Same principle for "plus max" (Samsung's S23 FE / Ultra
# etc. get handled below via the standalone " max" branch). "Pro Max" as
# a canonical Apple suffix was the specific bug: without it, iPhone 14 Pro
# and iPhone 14 Pro Max both extracted model="iphone 14 pro" and merged
# into one Product spanning ~KSh 60k–205k on the same page.
_MODEL_RE = re.compile(
    r"\b([a-z]+\s*\d{1,4}\s*[a-z]?"
    # Longest phrases first — regex alternation is left-to-right and
    # non-backtracking here. "pro max" must beat plain "pro", "pro plus"
    # must beat plain "pro", otherwise "iPhone 14 Pro Max" and
    # "Infinix Hot 50 Pro Plus" get their suffix stripped.
    r"(?:\s*pro\s*max|\s*pro\s*plus|\s*plus\s*max"
    r"|\s*pro|\s*plus|\s*ultra|\s*lite|\s*max|\s*\+)?)\b",
    re.IGNORECASE,
)
# Collapse "30 C" → "30c" so cosmetic spacing doesn't split canonical keys.
_TIGHTEN_MODEL_RE = re.compile(r"(\d+)\s+([a-z])\b", re.IGNORECASE)


def _find_brand(title: str) -> tuple[str | None, str | None]:
    """Return (canonical_brand, raw_token_found). They differ when the token is an alias."""
    for token in title.split():
        if token in KNOWN_BRANDS:
            return BRAND_ALIASES.get(token, token), token
    return None, None


def _find_storage(title: str) -> tuple[int | None, int | None]:
    """Return (storage_gb, ram_gb).

    Strategy:
      1. Prefer an explicit pair separated by + or / (highest confidence).
      2. Otherwise collect every "<N>GB" mention and infer:
         storage = max value >= 32GB, RAM = min value in [2,32).
    """
    m = _STORAGE_PAIR_RE.search(title)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        ram, storage = sorted([a, b])
        if _STORAGE_MIN_GB <= storage <= _STORAGE_MAX_GB and _RAM_MIN_GB <= ram <= _RAM_MAX_GB:
            return storage, ram
        # else: nonsensical range — fall through to the gb-anchored fallback

    matches = [int(x) for x in _ALL_GB_RE.findall(title)]
    if not matches:
        return None, None
    big = [x for x in matches if x >= _STORAGE_MIN_GB]
    small = [x for x in matches if _RAM_MIN_GB <= x < _STORAGE_MIN_GB]
    storage = max(big) if big else None
    ram = min(small) if small else None
    return storage, ram


def _strip_noise(title: str) -> str:
    parts = [t for t in title.split() if t and t not in NOISE_TOKENS]
    return " ".join(parts)


def _find_model(title: str) -> str | None:
    """We don't strip the brand from the title — for aliases like `iPhone` or
    `Redmi` the alias word is part of the canonical model name, and stripping
    it would lose the model entirely. The regex naturally skips the brand token
    because it requires a digit in the match."""
    text = _strip_noise(title)
    m = _MODEL_RE.search(text)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1)).strip()
    tightened = _TIGHTEN_MODEL_RE.sub(r"\1\2", raw)
    # If the character right after the matched span is "+", the model has
    # a plus suffix (e.g. "S24+"). Regex \b can't capture it: "+" sits
    # between two non-word chars (digit + space), so \b fails and the
    # match stops at the digit. Detect it manually so slugify doesn't
    # collapse "S24+" and plain "S24" into the same canonical key.
    if text[m.end(1):m.end(1) + 1] == "+":
        tightened = tightened + " plus"
    tightened = re.sub(r"\+\s*$", " plus", tightened).strip()
    return tightened


def parse_title(title: str, description: str | None = None) -> ParsedTitle:
    cleaned = clean_title(title)

    brand, _ = _find_brand(cleaned)
    storage, ram = _find_storage(cleaned)
    model = _find_model(cleaned)

    # Reject phone-adjacent accessories: the title matches an accessory
    # marker AND we found no phone-spec signal (no storage_gb, no ram_gb).
    # Real phone titles almost always mention at least one; accessories
    # like "Belkin Iphone Case For Iphone 14" mention neither. Combining
    # the two checks means "Free Charger" bundle language in a real phone
    # listing (e.g. "Samsung Galaxy A03 Core 32GB+2GB RAM (Free Charger)")
    # doesn't get rejected.
    if _is_phone_accessory(cleaned) and not (storage or ram):
        return ParsedTitle()

    # Description-aware spec fallback. Some merchant titles are terse
    # ("iPhone 14 Pro" with no storage/RAM), which leaves canonical_key
    # under-specified vs. a fuller listing ("iPhone 14 Pro 128GB 6GB
    # RAM"). If the scraper managed to capture a description alongside
    # the title, mine that for storage/RAM as a secondary source. We
    # only harvest numeric spec signals — NEVER re-run accessory
    # detection on the description, because bundle blurbs like "ships
    # with a free case" would wrongly veto a real phone.
    if description and not (storage and ram):
        d_cleaned = clean_title(description)
        d_storage, d_ram = _find_storage(d_cleaned)
        storage = storage or d_storage
        ram = ram or d_ram

    specs: dict = {}
    if storage:
        specs["storage_gb"] = storage
    if ram:
        specs["ram_gb"] = ram

    if not (brand and model):
        return ParsedTitle(brand=brand, model=model, specs=specs)

    parts = [slugify(brand), slugify(model)]
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
