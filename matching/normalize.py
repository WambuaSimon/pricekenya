"""Deterministic v0 product matching.

Goal: turn merchant listing titles like
  "Tecno Spark 30C 5G - 8GB+256GB - Black"
  "Tecno Spark 30 C (256+8) - Magic Skin Black"
into the same canonical key:
  "tecno|spark-30c|256|8"

This is intentionally simple. Anything ambiguous (no model number found, no
storage extracted) should be flagged for manual review or an LLM second pass —
that hook lives in match_or_create_product but is not implemented in v0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from slugify import slugify

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

# Words that often appear next to the brand and pad the model — strip before model extraction.
NOISE_TOKENS = {"galaxy", "smartphone", "phone", "5g", "4g", "lte", "dual", "sim"}

# "8GB+256GB", "8/256", "8 + 256", etc. — high-confidence storage pair.
# The leading (?<!\.) rejects matches like "2.0+12" (from "Battery 2.0+12 MONTHS WARRANTY")
# where the "0" would otherwise be captured as RAM.
_STORAGE_PAIR_RE = re.compile(
    r"(?<!\.)(?P<a>\d{1,3})\s*(?:gb)?\s*[+/]\s*(?P<b>\d{2,4})\s*(?:gb)?",
    re.IGNORECASE,
)
# Plausible bounds for real phone RAM/storage. Matches outside these are treated
# as coincidental number patterns, not specs.
_STORAGE_MIN_GB, _STORAGE_MAX_GB = 16, 4096
_RAM_MIN_GB, _RAM_MAX_GB = 2, 32
# Every "<N>gb" mention; used as a fallback when no +/ separator is present.
_ALL_GB_RE = re.compile(r"(\d{1,4})\s*gb", re.IGNORECASE)
# Model token e.g. "Spark 30C", "Camon 30", "A54", "Note 13 Pro"
_MODEL_RE = re.compile(
    r"\b([a-z]+\s*\d{1,4}\s*[a-z]?(?:\s*pro|\s*plus|\s*ultra|\s*lite|\s*\+)?)\b",
    re.IGNORECASE,
)
# Collapse "30 C" → "30c" (digit followed by space then a single trailing letter token).
_TIGHTEN_MODEL_RE = re.compile(r"(\d+)\s+([a-z])\b", re.IGNORECASE)


@dataclass
class ParsedTitle:
    brand: str | None
    model: str | None
    storage_gb: int | None
    ram_gb: int | None
    canonical_key: str | None


def _clean(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower()).strip()


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


def _find_model(title: str, brand_token: str | None) -> str | None:
    """Find the model token. We *don't* strip the brand — for Apple/Xiaomi
    aliases (iPhone, Redmi) the alias word is part of the canonical model name,
    and stripping it would lose the model entirely. The regex naturally skips
    the brand token because it requires a digit in the match."""
    text = _strip_noise(title)
    m = _MODEL_RE.search(text)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1)).strip()
    return _TIGHTEN_MODEL_RE.sub(r"\1\2", raw)


def parse_title(title: str) -> ParsedTitle:
    cleaned = _clean(title)
    brand, brand_token = _find_brand(cleaned)
    storage, ram = _find_storage(cleaned)
    model = _find_model(cleaned, brand_token)

    if not (brand and model):
        return ParsedTitle(brand, model, storage, ram, None)

    parts = [slugify(brand), slugify(model)]
    if storage:
        parts.append(str(storage))
    if ram:
        parts.append(str(ram))
    return ParsedTitle(brand, model, storage, ram, "|".join(parts))
