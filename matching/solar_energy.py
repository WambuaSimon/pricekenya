"""Solar + power-backup matcher: inverters, panels, batteries.

Three product families that share matcher shape (brand + numeric spec + optional
subtype), so we keep them in one module with `expected_type` dispatch — same
pattern as `small_appliances.py`.

**Kenyan market notes:**
- Inverters: dominated by brands like Growatt, Must, Felicity, MECER, SunPower,
  and Hotpoint's own Sollatek / K-Elec labels. Watt rating (300W → 10kW) is the
  dominant buyer spec; topology (pure sine / modified / hybrid) matters
  secondarily. "Hybrid" inverters bundle a solar charge controller.
- Solar panels: monocrystalline mostly; wattage (100W → 550W) drives the buy.
  Brand matters less than wattage — buyers ask for "400W panel", not a model.
- Solar batteries: chemistry (LiFePO4 vs lead-acid/AGM/gel) is the big split;
  capacity in Ah (30Ah → 300Ah) is the primary spec. Voltage (12V, 24V, 48V)
  is a secondary key when present.

**Rejects:** the merchants leak accessories (mounting rails, MC4 connectors,
inline fuses, cable) into these categories. We reject titles that don't carry
the expected-type keywords, and specifically-named accessories.
"""

from __future__ import annotations

import re

from matching.base import ParsedTitle, clean_title, slugify

# Compound-brand phrases first so "Vision Plus", "Blue Nova", etc. don't get
# collapsed to just their first token.
COMPOUND_BRANDS: list[tuple[str, str]] = [
    ("vision plus", "vision-plus"),
    ("blue nova", "bluenova"),
    ("felicity solar", "felicity"),
    ("sun power", "sunpower"),
]

# Single-token brands. Mix of solar-specific players (Growatt, Felicity, Must,
# MECER, Victron, EcoFlow, Jackery), Kenyan/regional (Sollatek, K-Elec, SolarMax,
# Simba), and Chinese OEMs common at Jumia/Kilimall.
KNOWN_BRANDS: set[str] = {
    # Solar-specific / inverter specialists
    "growatt", "must", "mecer", "felicity", "victron", "sunpower", "solax",
    "srne", "hopewind", "epever", "epsolar", "voltronic", "axpert", "sma",
    "power-master", "powmr", "goodwe", "deye", "polinovel", "pylontech",
    "narada", "hoppecke", "trojan", "jinko", "canadian", "longi", "trina",
    "risen", "ja", "yingli", "sunpal", "wattsun",
    # Portable / power stations
    "ecoflow", "jackery", "bluetti", "anker", "goal-zero", "geneverse",
    # Kenyan / regional / brand imports
    "sollatek", "k-elec", "solarmax", "solarworld", "simba", "chloride",
    "ariete", "century", "victronx", "ecomax", "solaric",
    # Global appliance brands that also carry solar/inverter lines
    "hisense", "samsung", "lg", "haier", "bosch", "philips", "black+decker",
    "sinbo", "nunix", "mika", "ramtons", "bruhm", "von", "ailyons", "nobel",
    "smartec", "syinix",
}


CONDITION_KEYWORDS: dict[str, str] = {
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "renewed": "refurbished",
    "used": "used",
    "second hand": "used",
    "brand new": "new",
}

# Type-name keywords. Ordered longest-first so "hybrid inverter" beats "inverter".
INVERTER_MARKERS = (
    "hybrid inverter", "off-grid inverter", "off grid inverter",
    "grid-tie inverter", "grid tie inverter", "pure sine wave inverter",
    "solar inverter", "power inverter", "car inverter", "inverter",
)
PANEL_MARKERS = (
    "solar panel", "photovoltaic panel", "pv panel", "solar module",
    "monocrystalline panel", "polycrystalline panel", "solar mono",
    "solar poly",
)
BATTERY_MARKERS = (
    "solar battery", "solar-battery", "lithium battery", "lifepo4 battery",
    "lifepo4", "gel battery", "agm battery", "deep cycle battery",
    "deep-cycle battery", "sealed lead acid", "sla battery", "vrla battery",
    "tubular battery",
    # Bare "battery" is too generic — matched last via a stricter check.
)

# Solar "kits" bundle panel + battery + inverter + wire into one SKU. They
# don't cleanly belong to any of the three leaves — a 300W kit would
# collide-key with a bare 300W panel and the buyer intent is different. We
# reject them from all three leaves. A dedicated `solar-kits` leaf could
# consume them later.
_KIT_MARKERS = (
    "full kit", "fullkit", "solar kit", "solar home kit", "solar system kit",
    "combo kit", "kit + ", "kit +",
    " with battery and inverter", "panel + battery", "with inverter and",
)

# Per-type non-match markers: accessories that leak into the merchant feed but
# aren't the actual product we're indexing.
NON_MATCHES: dict[str, tuple[str, ...]] = {
    "inverter": (
        "inverter cable", "inverter fuse", "inverter fan", "inverter remote",
        "inverter transformer", "inverter board", "inverter stand",
        "inverter cover", "inverter accessory", "inverter accessories",
        "spare part",
    ),
    "solar-panel": (
        "panel mounting", "panel bracket", "panel connector", "mc4 connector",
        "panel cable", "panel cleaner", "panel stand", "panel frame",
        "panel accessory", "panel accessories", "spare part", "panel meter",
    ),
    "solar-battery": (
        "battery cable", "battery terminal", "battery holder", "battery charger",
        "battery box", "battery tester", "battery meter", "battery clamp",
        "battery accessory", "battery accessories", "car battery", "aa battery",
        "aaa battery", "cmos battery", "watch battery", "spare part",
        "power bank",  # power banks are phone-scale, not solar-scale
    ),
}


# Watts. Also match "kW" / "kva" and convert. Range 100W..15000W plausible for
# inverters / panels; anything else is likely an accessory/misparse.
_WATTS_RE = re.compile(
    r"(\d{1,5}(?:\.\d+)?)\s*(kw|kva|va|watts?|w)\b",
    re.IGNORECASE,
)
# Amp-hours: 12V/24V/48V batteries commonly 30Ah..500Ah.
_AH_RE = re.compile(r"(\d{2,4})\s*(?:ah|amp[- ]?hours?)", re.IGNORECASE)
# System voltage: 12V, 24V, 48V (and rare 96V / 6V for cheap AGM). Range
# constrained so a random 220V grid-voltage doesn't match.
_VOLTAGE_RE = re.compile(r"\b(6|12|24|36|48|96)\s*v(?:olt)?\b", re.IGNORECASE)

# Inverter topology.
_TOPOLOGY_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("hybrid", ("hybrid",)),
    ("pure-sine", ("pure sine wave", "pure-sine", "pure sinewave", "psw")),
    ("modified", ("modified sine", "modified-sine", "modified sinewave")),
    ("off-grid", ("off-grid", "off grid")),
    ("grid-tie", ("grid-tie", "grid tie", "on-grid", "on grid")),
]

# Panel chemistry / cell type.
_PANEL_TYPE_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("mono", ("monocrystalline", "mono-crystalline", "mono crystalline", "mono")),
    ("poly", ("polycrystalline", "poly-crystalline", "poly crystalline", "poly")),
    ("bifacial", ("bifacial",)),
    ("thin-film", ("thin film", "thin-film", "amorphous")),
]

# Battery chemistry.
_BATTERY_CHEMISTRY_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("lifepo4", ("lifepo4", "lfp", "lithium iron phosphate")),
    ("lithium", ("lithium-ion", "lithium ion", "li-ion", "lithium")),
    ("gel", ("gel battery", "gel-battery", "gel type")),
    ("agm", ("agm battery", "agm-battery", "absorbed glass mat")),
    ("vrla", ("vrla",)),
    ("tubular", ("tubular",)),
    ("lead-acid", ("lead acid", "lead-acid", "sla", "sealed lead")),
]


def _find_brand(cleaned: str) -> str | None:
    for phrase, canonical in COMPOUND_BRANDS:
        if phrase in cleaned:
            return canonical
    for tok in cleaned.split():
        tok = re.sub(r"[^a-z0-9-+]", "", tok)
        if tok in KNOWN_BRANDS:
            return tok
    return None


def _find_condition(cleaned: str) -> str:
    for kw, cond in CONDITION_KEYWORDS.items():
        if kw in cleaned:
            return cond
    return "new"


def _find_watts(cleaned: str) -> int | None:
    """Return the primary watt rating. kW/kVA get converted to W.

    We prefer the FIRST plausible match — inverter titles often carry both a
    system watt rating (e.g., 3000W) and secondary numbers (charge current,
    battery bank size) that shouldn't fool us.
    """
    for m in _WATTS_RE.finditer(cleaned):
        raw = float(m.group(1))
        unit = m.group(2).lower()
        if unit in ("kw", "kva"):
            watts = int(raw * 1000)
        elif unit == "va":
            # Rough conversion; enough for canonical grouping.
            watts = int(raw * 0.8)
        else:
            # `w` or `watts`
            watts = int(raw)
        if 50 <= watts <= 15000:
            return watts
    return None


def _find_ah(cleaned: str) -> int | None:
    for m in _AH_RE.finditer(cleaned):
        n = int(m.group(1))
        if 5 <= n <= 1000:
            return n
    return None


def _find_voltage(cleaned: str) -> int | None:
    for m in _VOLTAGE_RE.finditer(cleaned):
        return int(m.group(1))
    return None


def _find_from_markers(
    cleaned: str, markers: list[tuple[str, tuple[str, ...]]]
) -> str | None:
    for name, phrases in markers:
        if any(p in cleaned for p in phrases):
            return name
    return None


def _title_looks_like(expected: str, cleaned: str) -> bool:
    markers = {
        "inverter": INVERTER_MARKERS,
        "solar-panel": PANEL_MARKERS,
        "solar-battery": BATTERY_MARKERS,
    }[expected]
    if any(m in cleaned for m in markers):
        return True
    # Stricter fallback for solar-battery: "battery" alone is too broad, but
    # a battery next to a solar/deep-cycle spec is a strong signal.
    if expected == "solar-battery" and "battery" in cleaned:
        if _find_ah(cleaned) or "solar" in cleaned or "deep cycle" in cleaned:
            return True
    return False


def parse_title(title: str, expected_type: str) -> ParsedTitle:
    if expected_type not in ("inverter", "solar-panel", "solar-battery"):
        return ParsedTitle()

    cleaned = clean_title(title)

    # Reject kits — different buyer intent, would collide-key with pure products.
    for marker in _KIT_MARKERS:
        if marker in cleaned:
            return ParsedTitle()

    # Reject non-matches (accessories, wrong products in the feed).
    for marker in NON_MATCHES.get(expected_type, ()):
        if marker in cleaned:
            return ParsedTitle()

    # Reject titles that don't even mention the expected type.
    if not _title_looks_like(expected_type, cleaned):
        return ParsedTitle()

    brand = _find_brand(cleaned)
    if not brand:
        return ParsedTitle()

    condition = _find_condition(cleaned)
    specs: dict = {"condition": condition}
    parts: list[str] = [slugify(brand)]
    display_bits: list[str] = [brand.replace("-", " ").title()]

    if expected_type == "inverter":
        watts = _find_watts(cleaned)
        if not watts:
            # Wattage is the primary group key for inverters — without it we
            # can't build a stable canonical.
            return ParsedTitle()
        topology = _find_from_markers(cleaned, _TOPOLOGY_MARKERS)
        voltage = _find_voltage(cleaned)
        parts.append(f"{watts}w")
        specs["watts"] = watts
        if topology:
            parts.append(topology)
            specs["topology"] = topology.replace("-", " ").title()
        if voltage:
            specs["system_voltage_v"] = voltage
        display_bits.append(f"{watts}W")
        if topology:
            display_bits.append(topology.replace("-", " ").title())
        display_bits.append("Inverter")
        if voltage:
            display_bits.append(f"({voltage}V)")

    elif expected_type == "solar-panel":
        watts = _find_watts(cleaned)
        if not watts:
            return ParsedTitle()
        cell = _find_from_markers(cleaned, _PANEL_TYPE_MARKERS)
        parts.append(f"{watts}w")
        specs["watts"] = watts
        if cell:
            parts.append(cell)
            specs["cell_type"] = cell.title()
        display_bits.append(f"{watts}W")
        if cell:
            display_bits.append(cell.title())
        display_bits.append("Solar Panel")

    elif expected_type == "solar-battery":
        ah = _find_ah(cleaned)
        chemistry = _find_from_markers(cleaned, _BATTERY_CHEMISTRY_MARKERS)
        voltage = _find_voltage(cleaned)
        # Batteries need at LEAST one of {Ah, chemistry} to key on — without
        # either we're guessing.
        if not ah and not chemistry:
            return ParsedTitle()
        if ah:
            parts.append(f"{ah}ah")
            specs["capacity_ah"] = ah
        if chemistry:
            parts.append(chemistry)
            specs["chemistry"] = chemistry.replace("-", " ").upper()
        if voltage:
            parts.append(f"{voltage}v")
            specs["voltage_v"] = voltage
        display_bits.append("Solar Battery")
        if ah:
            display_bits.append(f"{ah}Ah")
        if chemistry:
            display_bits.append(chemistry.replace("-", " ").upper())
        if voltage:
            display_bits.append(f"({voltage}V)")

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
