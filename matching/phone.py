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
_MODEL_RE = re.compile(
    r"\b([a-z]+\s*\d{1,4}\s*[a-z]?(?:\s*pro|\s*plus|\s*ultra|\s*lite|\s*\+)?)\b",
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
    return _TIGHTEN_MODEL_RE.sub(r"\1\2", raw)


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)
    brand, _ = _find_brand(cleaned)
    storage, ram = _find_storage(cleaned)
    model = _find_model(cleaned)

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
