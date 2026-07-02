"""Laptop-category title parser.

The Kenyan laptop market is heavily refurbished business-laptop resale
(EliteBook / ThinkPad / Latitude), so the matcher's design priorities are:

1. Infer brand from a well-known model line when the brand word is missing
   ("ThinkPad X270 8GB 256GB" → brand=lenovo).
2. Capture the model-line + variant as one canonical model token (elitebook-840-g3).
3. Include CPU family + generation in the canonical key — "i5 6th Gen" and
   "i5 8th Gen" are meaningfully different products at very different prices.
4. Include storage-type (SSD/HDD/eMMC) — same capacity SSD is worth 2x an HDD.
5. Include condition (new vs refurbished) — refurb sells at ~50% of new.

Anything without at least brand+model returns unparsed. This drops the flash
drives and mice that leak into merchants' "laptops" categories.
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title, slugify

# Brands seen in Kenyan retail. `macbook` is treated as an alias for `apple`.
KNOWN_BRANDS = {
    "hp", "lenovo", "dell", "apple", "macbook", "acer", "asus", "microsoft",
    "surface", "msi", "toshiba", "samsung", "huawei", "razer", "google",
    "chuwi", "gateway", "fujitsu", "nec",
}
BRAND_ALIASES = {
    "macbook": "apple",
    "surface": "microsoft",
}

# Model-line vocab per brand. When a title includes one of these words but no
# brand word, we infer the brand from the mapping below.
BRAND_MODEL_LINES = {
    "hp": {"elitebook", "probook", "pavilion", "envy", "spectre", "omen",
           "chromebook", "stream", "victus", "zbook", "workstation"},
    "lenovo": {"thinkpad", "ideapad", "yoga", "legion", "thinkbook"},
    "dell": {"latitude", "inspiron", "xps", "precision", "vostro", "alienware"},
    "apple": {"macbook"},
    "acer": {"aspire", "nitro", "predator", "swift", "travelmate"},
    "asus": {"rog", "zenbook", "vivobook", "tuf", "proart", "expertbook"},
    "microsoft": {"surface"},
    "msi": {"modern", "prestige", "katana", "stealth", "raider", "vector"},
    "toshiba": {"portege", "satellite", "tecra"},
    "samsung": {"galaxy"},
}
# Reverse map: model line word → canonical brand.
LINE_TO_BRAND: dict[str, str] = {
    line: brand for brand, lines in BRAND_MODEL_LINES.items() for line in lines
}

CONDITION_KEYWORDS = {
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "renewed": "refurbished",
    "used": "used",
    "second hand": "used",
    "brand new": "new",
    "new arrival": "new",
}

# CPU family regexes. Ordered so multi-word alternatives are tried first.
_CPU_FAMILY_RE = re.compile(
    r"\b(core\s*i[3579]|i[3579]|ryzen\s*[3579]|celeron|pentium|athlon|apple\s*m[1234]|m[1234])\b",
    re.IGNORECASE,
)
# Intel generation: "6th gen", "10th generation", or embedded in SKU like "i5-8250U" (8000-series = 8th gen).
_CPU_GEN_TEXT_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s*gen(?:eration)?", re.IGNORECASE)
_CPU_SKU_RE = re.compile(r"\bi[3579][- ]?(\d{4,5})[a-z]{0,3}\b", re.IGNORECASE)

_RAM_RE = re.compile(r"(\d{1,3})\s*gb(?:\s*(?:ddr|lpddr)\d*)?\s*ram", re.IGNORECASE)
_RAM_ALT_RE = re.compile(r"\bram[:\s]*(\d{1,3})\s*gb", re.IGNORECASE)
_STORAGE_RE = re.compile(
    r"(\d{2,4})\s*(gb|tb)\s*(ssd|hdd|emmc|nvme)?",
    re.IGNORECASE,
)
# Combined "8GB+256GB SSD" / "8GB / 256GB" pattern — helpful when RAM/storage aren't labelled.
_RAM_STORAGE_PAIR_RE = re.compile(
    r"(?<!\.)(\d{1,2})\s*gb\s*[+/]\s*(\d{2,4})\s*(gb|tb)?\s*(ssd|hdd|emmc)?",
    re.IGNORECASE,
)

# Plausible ranges.
_RAM_MIN, _RAM_MAX = 2, 128
_STORAGE_MIN_GB, _STORAGE_MAX_GB = 16, 8192
# 1 TB = 1024 GB in the sizes we care about here.
_TB_TO_GB = 1024

# "pro" is deliberately NOT in this set — it's a legitimate variant token
# for MacBook Pro. Same for "10"/"11" which are legitimate Chromebook 11 /
# EliteBook 1040 variants — Windows edition disambiguation happens at CPU/OS
# extraction time, not by stripping noise tokens.
NOISE_TOKENS = {
    "laptop", "laptops", "notebook", "ultrabook", "computer", "pc",
    "brand", "intel", "amd", "windows", "win", "home",
    "the", "a", "with", "and", "for", "wi-fi", "wifi", "bluetooth", "webcam",
    "hd", "fhd", "uhd", "qhd", "ips", "touchscreen", "touch", "screen",
    "display", "inches", "inch", "black", "silver", "gray", "grey", "gold",
    "blue", "red", "months", "wrty", "warranty",
}

# Sub-line qualifiers we want to include in the model variant. "MacBook Pro"
# vs "MacBook Air" is a meaningful distinction that should show up in the key.
VARIANT_QUALIFIERS = {"pro", "air", "max", "mini", "ultra", "plus", "lite"}


def _find_brand(cleaned: str) -> tuple[str | None, str | None]:
    """Return (brand, brand_or_line_token_found).

    Falls back to model-line inference: "ThinkPad X270 ..." → lenovo.
    """
    tokens = cleaned.split()
    for tok in tokens:
        if tok in KNOWN_BRANDS:
            return BRAND_ALIASES.get(tok, tok), tok
        if tok in LINE_TO_BRAND:
            return LINE_TO_BRAND[tok], tok
    return None, None


_VARIANT_ALNUM_RE = re.compile(r"[a-z]{0,2}\d{2,5}[a-z]?")
_G_SUFFIX_RE = re.compile(r"g\d{1,2}")
_TOKEN_STRIP_RE = re.compile(r"[^a-z0-9-]")


def _collect_variants_forward(tokens: list[str], start: int, end: int) -> list[str]:
    """Walk tokens[start:end] left-to-right, collecting variant-shaped tokens."""
    parts: list[str] = []
    for j in range(start, min(end, len(tokens))):
        t = tokens[j]
        if not t or t in NOISE_TOKENS:
            continue
        # Qualifier ("pro"/"air") only counts as the first slot.
        if t in VARIANT_QUALIFIERS and j == start:
            parts.append(t)
            continue
        if _VARIANT_ALNUM_RE.fullmatch(t) or _G_SUFFIX_RE.fullmatch(t):
            parts.append(t)
            continue
        if parts:
            break  # end of a continuous variant run
    return parts


def _find_model_line_and_variant(cleaned: str, brand: str) -> tuple[str | None, str | None]:
    """Find the model line + its variant.

    We prefer variants *after* the line word (`elitebook 840 g3`), but fall
    back to a look-back window when the merchant wrote the line word *after*
    the model number ("HP Laptops 840 8GB RAM 256GB SSD Elitebook Refurbished"
    is real Kilimall data). Tokens are stripped of trailing punctuation before
    the shape check so "820," doesn't get dropped.
    """
    lines = BRAND_MODEL_LINES.get(brand, set())
    if not lines:
        return None, None

    tokens = [_TOKEN_STRIP_RE.sub("", t) for t in cleaned.split()]

    def _looks_weak(parts: list[str]) -> bool:
        """A single bare 2-digit token is more likely a screen size (14'') than
        a real model number, so we treat it as a weak match and prefer a
        backward-window alternative if one exists."""
        return len(parts) == 1 and parts[0].isdigit() and len(parts[0]) == 2

    for i, tok in enumerate(tokens):
        if tok not in lines:
            continue
        # Forward window first — the natural word order for structured titles.
        variant_parts = _collect_variants_forward(tokens, i + 1, i + 6)

        # If forward gave us nothing (or only a weak 2-digit match), try the
        # backward window. Some merchants — notably Kilimall — put the model
        # number before the line word: "HP Laptops 840 8GB … Elitebook".
        if not variant_parts or _looks_weak(variant_parts):
            backward = list(reversed(tokens[max(0, i - 5) : i]))
            back_parts = list(reversed(_collect_variants_forward(backward, 0, len(backward))))
            if back_parts and not _looks_weak(back_parts):
                variant_parts = back_parts

        if variant_parts:
            return tok, "-".join(variant_parts)
        return tok, None
    return None, None


def _find_cpu(cleaned: str) -> tuple[str | None, int | None]:
    """Return (cpu_family, cpu_gen). Family is e.g. 'i5', 'celeron', 'm2'."""
    fam_match = _CPU_FAMILY_RE.search(cleaned)
    family = None
    if fam_match:
        raw = fam_match.group(1).lower().replace(" ", "").replace("core", "").replace("apple", "")
        # Normalize: 'ryzen5' → 'ryzen-5', 'i5' → 'i5'
        if raw.startswith("ryzen"):
            family = "ryzen-" + raw.replace("ryzen", "")
        elif raw.startswith("i") and raw[1:].isdigit():
            family = raw
        else:
            family = raw

    gen: int | None = None
    m = _CPU_GEN_TEXT_RE.search(cleaned)
    if m:
        gen_candidate = int(m.group(1))
        if 1 <= gen_candidate <= 20:
            gen = gen_candidate
    if gen is None:
        m = _CPU_SKU_RE.search(cleaned)
        if m:
            # First digit of a 4-digit Intel SKU is the generation (i5-8250 = 8th gen).
            first = int(m.group(1)[0])
            if 3 <= first <= 20:
                gen = first
    return family, gen


def _find_ram(cleaned: str) -> int | None:
    m = _RAM_RE.search(cleaned)
    if m:
        v = int(m.group(1))
        if _RAM_MIN <= v <= _RAM_MAX:
            return v
    m = _RAM_ALT_RE.search(cleaned)
    if m:
        v = int(m.group(1))
        if _RAM_MIN <= v <= _RAM_MAX:
            return v
    # "8GB+256GB" style — take the smaller as RAM.
    m = _RAM_STORAGE_PAIR_RE.search(cleaned)
    if m:
        a = int(m.group(1))
        if _RAM_MIN <= a <= _RAM_MAX:
            return a
    return None


_STORAGE_WITH_TYPE_RE = re.compile(
    r"(\d{2,4})\s*(gb|tb)?\s*(ssd|hdd|emmc|nvme)",
    re.IGNORECASE,
)


def _find_storage(cleaned: str, ram_gb: int | None) -> tuple[int | None, str | None]:
    """Return (storage_gb, storage_type). Type is ssd/hdd/emmc or None.

    Priority order:
      1. `<N> [GB|TB]? SSD/HDD/eMMC` — highest confidence (type explicit)
      2. `<N>GB` bare, but only when the number is >= 128 (below that it's
         almost certainly RAM, not storage)
      3. `<N>GB+<M>GB` pair
    RAM's value is explicitly excluded from all matches to avoid capturing
    "8GB RAM" or "16GBRAM" as storage.
    """
    # Priority 1: explicit type
    for m in _STORAGE_WITH_TYPE_RE.finditer(cleaned):
        n = int(m.group(1))
        unit = (m.group(2) or "gb").lower()
        t = m.group(3).lower()
        gb = n * _TB_TO_GB if unit == "tb" else n
        if _STORAGE_MIN_GB <= gb <= _STORAGE_MAX_GB and gb != ram_gb:
            return gb, t

    # Priority 2: bare GB/TB only when >= 128 (below is almost always RAM)
    for m in _STORAGE_RE.finditer(cleaned):
        n = int(m.group(1))
        unit = m.group(2).lower()
        gb = n * _TB_TO_GB if unit == "tb" else n
        if 128 <= gb <= _STORAGE_MAX_GB and gb != ram_gb:
            return gb, None

    # Priority 3: pair "8GB+256GB SSD"
    m = _RAM_STORAGE_PAIR_RE.search(cleaned)
    if m:
        n = int(m.group(2))
        unit = (m.group(3) or "gb").lower()
        t = (m.group(4) or "").lower() or None
        gb = n * _TB_TO_GB if unit == "tb" else n
        if _STORAGE_MIN_GB <= gb <= _STORAGE_MAX_GB and gb != ram_gb:
            return gb, t
    return None, None


def _find_condition(cleaned: str) -> str:
    for kw, cond in CONDITION_KEYWORDS.items():
        if kw in cleaned:
            return cond
    return "new"


def parse_title(title: str) -> ParsedTitle:
    cleaned = clean_title(title)
    brand, _ = _find_brand(cleaned)
    if not brand:
        return ParsedTitle()

    line, variant = _find_model_line_and_variant(cleaned, brand)
    if not (line or variant):
        # Without a recognizable model line/variant, we don't have a stable key.
        return ParsedTitle(brand=brand)

    model_slug = "-".join(x for x in [line, variant] if x)
    cpu_family, cpu_gen = _find_cpu(cleaned)
    ram = _find_ram(cleaned)
    storage_gb, storage_type = _find_storage(cleaned, ram)
    condition = _find_condition(cleaned)

    # Canonical key: brand | model | cpu[-gen] | ram | storage[-type] | condition-if-refurb
    key_parts = [slugify(brand), slugify(model_slug)]
    if cpu_family:
        key_parts.append(f"{cpu_family}-{cpu_gen}" if cpu_gen else cpu_family)
    if ram:
        key_parts.append(str(ram))
    if storage_gb:
        stor_part = f"{storage_gb}-{storage_type}" if storage_type else str(storage_gb)
        key_parts.append(stor_part)
    if condition != "new":
        key_parts.append(condition)

    specs: dict = {}
    if cpu_family:
        specs["cpu"] = f"{cpu_family.upper()} ({cpu_gen}th gen)" if cpu_gen else cpu_family.upper()
    if ram:
        specs["ram_gb"] = ram
    if storage_gb:
        specs["storage_gb"] = storage_gb
    if storage_type:
        specs["storage_type"] = storage_type.upper()
    specs["condition"] = condition

    display_bits = [
        brand.title(),
        (line.title() if line else ""),
        (variant.upper() if variant else ""),
        (specs.get("cpu") or ""),
        (f"{ram}/{storage_gb}GB" if ram and storage_gb else (f"{storage_gb}GB" if storage_gb else "")),
        (specs.get("storage_type") or ""),
        ("Refurbished" if condition == "refurbished" else ""),
    ]
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=model_slug,
        canonical_key="|".join(key_parts),
        specs=specs,
        display_title=display or None,
    )
