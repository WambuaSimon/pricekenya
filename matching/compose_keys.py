"""Per-category canonical-key composers used by the LLM extraction fallback.

The regex parsers in this package build their own ParsedTitle at the end of
each `parse_title()`. When a title trips the regex, the LLM fallback in
`matching.llm_extract` produces a structured dict of pieces (brand + specs) and
hands them to the corresponding `compose_<slug>` here.

For LLM-parsed and regex-parsed products to merge on the same `canonical_key`,
these composers MUST emit the same key format as the equivalent regex parser.
That parity is guarded by tests in `tests/test_compose_parity.py`. If a parser
adds/changes a spec that participates in its key, the corresponding composer
here must be updated and the parity test extended.

Each composer accepts a permissive dict — missing / None fields are tolerated
and skipped. Composers return `ParsedTitle()` (unparsed) when they don't have
enough signal to build a stable key.
"""

from __future__ import annotations

from typing import Any

from matching.base import ParsedTitle, slugify

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str | None:
    """Lowercase-and-strip a string field. Returns None for empty/None/non-str."""
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def _slug(value: Any) -> str | None:
    n = _norm(value)
    return slugify(n) if n else None


def _title(text: str | None) -> str:
    return (text or "").replace("-", " ").title().strip()


def _fmt_capacity(value: float) -> str:
    return str(int(value)) if float(value) == int(value) else str(value)


# ---------------------------------------------------------------------------
# Phones (matching/phone.py)
# key: brand|model[|storage_gb][|ram_gb]
# ---------------------------------------------------------------------------


def compose_phones(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    model = _norm(pieces.get("model"))
    if not (brand and model):
        return ParsedTitle()

    # Apply the same brand aliases the regex parser uses so LLM-emitted
    # brands ("iphone", "redmi", "pixel") canonicalise to their parent
    # brand ("apple", "xiaomi", "google"). Without this, two listings for
    # the same iPhone SKU split when one merchant title said "Apple" and
    # the LLM read "iPhone" as the brand token.
    from matching.phone import BRAND_ALIASES

    brand = BRAND_ALIASES.get(brand, brand)

    storage = pieces.get("storage_gb")
    ram = pieces.get("ram_gb")

    specs: dict = {}
    if storage:
        specs["storage_gb"] = int(storage)
    if ram:
        specs["ram_gb"] = int(ram)

    parts = [slugify(brand), slugify(model)]
    if storage:
        parts.append(str(int(storage)))
    if ram:
        parts.append(str(int(ram)))

    suffix = (
        f"{int(ram)}/{int(storage)}GB"
        if storage and ram
        else (f"{int(storage)}GB" if storage else "")
    )
    display = " ".join(x for x in [brand.title(), model.title(), suffix] if x).strip()
    return ParsedTitle(
        brand=brand,
        model=model,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=display or None,
    )


# ---------------------------------------------------------------------------
# Tablets (matching/tablet.py)
# key: brand|model[|<size>in][|storage_gb][|ram_gb]
# ---------------------------------------------------------------------------


def compose_tablets(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    model = _norm(pieces.get("model"))
    if not (brand and model):
        return ParsedTitle()

    size = pieces.get("screen_inches")
    storage = pieces.get("storage_gb")
    ram = pieces.get("ram_gb")

    specs: dict = {}
    if storage:
        specs["storage_gb"] = int(storage)
    if ram:
        specs["ram_gb"] = int(ram)
    if size:
        specs["screen_inches"] = float(size)

    parts = [slugify(brand), slugify(model)]
    if size:
        parts.append(f"{float(size):g}in")
    if storage:
        parts.append(str(int(storage)))
    if ram:
        parts.append(str(int(ram)))

    return ParsedTitle(
        brand=brand,
        model=model,
        canonical_key="|".join(parts),
        specs=specs,
    )


# ---------------------------------------------------------------------------
# Laptops (matching/laptop.py)
# key: brand|line[-variant][|cpu_family[-gen]][|ram][|storage[-type]][|condition-if-not-new]
# ---------------------------------------------------------------------------

_LAPTOP_CONDITIONS = {"new", "used", "refurbished"}


def compose_laptops(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    line = _norm(pieces.get("model_line"))
    variant = _norm(pieces.get("variant"))
    if not brand or not (line or variant):
        return ParsedTitle()

    model_slug = "-".join(x for x in [line, variant] if x)

    cpu_family = _norm(pieces.get("cpu_family"))
    cpu_gen = pieces.get("cpu_gen")
    ram = pieces.get("ram_gb")
    storage_gb = pieces.get("storage_gb")
    storage_type = _norm(pieces.get("storage_type"))
    condition = _norm(pieces.get("condition")) or "new"
    if condition not in _LAPTOP_CONDITIONS:
        condition = "new"

    key_parts = [slugify(brand), slugify(model_slug)]
    if cpu_family:
        key_parts.append(f"{cpu_family}-{int(cpu_gen)}" if cpu_gen else cpu_family)
    if ram:
        key_parts.append(str(int(ram)))
    if storage_gb:
        key_parts.append(
            f"{int(storage_gb)}-{storage_type}" if storage_type else str(int(storage_gb))
        )
    if condition != "new":
        key_parts.append(condition)

    specs: dict = {}
    if cpu_family:
        specs["cpu"] = (
            f"{cpu_family.upper()} ({int(cpu_gen)}th gen)" if cpu_gen else cpu_family.upper()
        )
    if ram:
        specs["ram_gb"] = int(ram)
    if storage_gb:
        specs["storage_gb"] = int(storage_gb)
    if storage_type:
        specs["storage_type"] = storage_type.upper()
    specs["condition"] = condition

    display_bits = [
        brand.title(),
        (line.title() if line else ""),
        (variant.upper() if variant else ""),
        specs.get("cpu") or "",
        (
            f"{int(ram)}/{int(storage_gb)}GB"
            if ram and storage_gb
            else (f"{int(storage_gb)}GB" if storage_gb else "")
        ),
        specs.get("storage_type") or "",
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


# ---------------------------------------------------------------------------
# TVs (matching/tv.py)
# key: brand|size|resolution?|panel?|smart-or-basic|condition-if-not-new?
# resolution only in key when it's fhd/4k/8k (see tv.py line 168)
# ---------------------------------------------------------------------------

_TV_KEY_RES = {"fhd", "4k", "8k"}


def compose_tvs(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    size = pieces.get("size_inches") or pieces.get("screen_inches")
    if not (brand and size):
        return ParsedTitle()

    resolution = _norm(pieces.get("resolution"))
    panel = _norm(pieces.get("panel"))
    smart = bool(pieces.get("smart"))
    condition = _norm(pieces.get("condition")) or "new"

    key_resolution = resolution if resolution in _TV_KEY_RES else None

    parts = [slugify(brand), str(int(size))]
    if key_resolution:
        parts.append(key_resolution)
    if panel:
        parts.append(panel)
    parts.append("smart" if smart else "basic")
    if condition != "new":
        parts.append(condition)

    specs: dict = {
        "screen_inches": int(size),
        "smart": smart,
        "condition": condition,
    }
    if resolution:
        specs["resolution"] = resolution.upper()
    if panel:
        specs["panel_type"] = panel.upper()

    display_bits = [
        brand.replace("-", " ").title(),
        f'{int(size)}"',
        (specs.get("resolution") or ""),
        (specs.get("panel_type") or ""),
        ("Smart TV" if smart else "TV"),
        ("Refurbished" if condition == "refurbished" else ""),
    ]
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=display,
    )


# ---------------------------------------------------------------------------
# Refrigerators (matching/refrigerator.py)
# key: brand|<cap>l[|doors][|condition-if-not-new]
# ---------------------------------------------------------------------------

_FRIDGE_DOORS = {"single", "double", "french", "sbs"}


def compose_refrigerators(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    capacity = pieces.get("capacity_liters")
    if not (brand and capacity):
        return ParsedTitle()

    doors = _norm(pieces.get("door_type"))
    if doors not in _FRIDGE_DOORS:
        doors = None
    condition = _norm(pieces.get("condition")) or "new"

    parts = [slugify(brand), f"{int(capacity)}l"]
    if doors:
        parts.append(doors)
    if condition != "new":
        parts.append(condition)

    specs: dict = {
        "capacity_liters": int(capacity),
        "condition": condition,
    }
    if doors:
        specs["door_type"] = doors.upper() if doors == "sbs" else doors.title()

    display_bits = [
        brand.replace("-", " ").title(),
        f"{int(capacity)}L",
        (specs.get("door_type") + " Door" if doors else ""),
        "Fridge",
        ("Refurbished" if condition == "refurbished" else ""),
    ]
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=display,
    )


# ---------------------------------------------------------------------------
# Freezers (no regex parser today — LLM-only leaf)
# key: brand|<cap>l[|freezer_type][|condition-if-not-new]
# ---------------------------------------------------------------------------

_FREEZER_TYPES = {"chest", "upright", "combi"}


def compose_freezers(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    capacity = pieces.get("capacity_liters")
    if not (brand and capacity):
        return ParsedTitle()

    freezer_type = _norm(pieces.get("freezer_type"))
    if freezer_type not in _FREEZER_TYPES:
        freezer_type = None
    condition = _norm(pieces.get("condition")) or "new"

    parts = [slugify(brand), f"{int(capacity)}l"]
    if freezer_type:
        parts.append(freezer_type)
    if condition != "new":
        parts.append(condition)

    specs: dict = {"capacity_liters": int(capacity), "condition": condition}
    if freezer_type:
        specs["freezer_type"] = freezer_type.title()

    display = " ".join(
        x
        for x in [
            brand.replace("-", " ").title(),
            f"{int(capacity)}L",
            (freezer_type.title() if freezer_type else ""),
            "Freezer",
            ("Refurbished" if condition == "refurbished" else ""),
        ]
        if x
    )
    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=display,
    )


# ---------------------------------------------------------------------------
# Water dispensers (no regex parser today — LLM-only leaf)
# key: brand[|model][|dispenser_type][|condition-if-not-new]
# ---------------------------------------------------------------------------

_DISPENSER_TYPES = {"hot-cold", "hot-normal", "hot-cold-normal", "bottom-load", "top-load"}


def compose_water_dispensers(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    if not brand:
        return ParsedTitle()

    model = _norm(pieces.get("model"))
    dispenser_type = _norm(pieces.get("dispenser_type"))
    if dispenser_type not in _DISPENSER_TYPES:
        dispenser_type = None
    condition = _norm(pieces.get("condition")) or "new"

    parts = [slugify(brand)]
    if model:
        parts.append(slugify(model))
    if dispenser_type:
        parts.append(dispenser_type)
    if condition != "new":
        parts.append(condition)

    if len(parts) == 1:
        return ParsedTitle()

    specs: dict = {"condition": condition}
    if dispenser_type:
        specs["dispenser_type"] = dispenser_type.replace("-", " ").title()
    if model:
        specs["model"] = model.upper()

    display = " ".join(
        x
        for x in [
            brand.replace("-", " ").title(),
            (model.upper() if model else ""),
            (specs.get("dispenser_type") or ""),
            "Water Dispenser",
            ("Refurbished" if condition == "refurbished" else ""),
        ]
        if x
    )
    return ParsedTitle(
        brand=brand,
        model=model,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=display,
    )


# ---------------------------------------------------------------------------
# Washers / Dryers (matching/washer.py)
# key: brand|<cap>kg|load_type[|automation][|with-dryer][|condition-if-not-new]
# ---------------------------------------------------------------------------

_LOAD_TYPES = {"twin-tub", "front", "top"}


def compose_washers_dryers(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    capacity = pieces.get("capacity_kg")
    load_type = _norm(pieces.get("load_type"))
    if not (brand and capacity and load_type in _LOAD_TYPES):
        return ParsedTitle()

    automation = _norm(pieces.get("automation")) or "unknown"
    if automation not in {"auto", "semi-auto", "unknown"}:
        automation = "unknown"
    if load_type == "twin-tub":
        automation = "semi-auto"

    has_dryer = bool(pieces.get("has_dryer"))
    condition = _norm(pieces.get("condition")) or "new"

    cap_str = _fmt_capacity(float(capacity))
    parts = [slugify(brand), f"{cap_str}kg", load_type]
    if automation != "unknown":
        parts.append(automation)
    if has_dryer:
        parts.append("with-dryer")
    if condition != "new":
        parts.append(condition)

    specs: dict = {
        "capacity_kg": float(capacity),
        "load_type": load_type.replace("-", " ").title(),
        "condition": condition,
    }
    if automation != "unknown":
        specs["automation"] = automation.replace("-", " ").title()
    if has_dryer:
        specs["has_dryer"] = True

    display_bits = [
        brand.replace("-", " ").title(),
        f"{cap_str}KG",
        specs["load_type"],
        specs.get("automation") or "",
        ("Washer-Dryer" if has_dryer else "Washing Machine"),
        ("Refurbished" if condition == "refurbished" else ""),
    ]
    display = " ".join(x for x in display_bits if x).strip()

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=display,
    )


# ---------------------------------------------------------------------------
# Cooking (matching/cooking.py)
# key varies by type; see cooking.py for exact shape.
# ---------------------------------------------------------------------------

_COOKING_TYPES = {"microwave", "cooker", "hob", "oven", "hot-plate"}
_COOKING_FUELS = {"gas", "electric", "induction"}
_COOKING_CONTROLS = {"digital", "manual"}


def compose_cooking(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    typ = _norm(pieces.get("type"))
    if not (brand and typ in _COOKING_TYPES):
        return ParsedTitle()

    condition = _norm(pieces.get("condition")) or "new"
    specs: dict = {"type": typ.title(), "condition": condition}
    parts = [slugify(brand), typ]
    display_bits = [brand.replace("-", " ").title()]

    if typ == "microwave":
        capacity = pieces.get("capacity_liters")
        control = _norm(pieces.get("control"))
        if control not in _COOKING_CONTROLS:
            control = None
        has_grill = bool(pieces.get("has_grill"))
        if capacity:
            parts.append(f"{int(capacity)}l")
            specs["capacity_liters"] = int(capacity)
            display_bits.append(f"{int(capacity)}L")
        if control:
            parts.append(control)
            specs["control"] = control.title()
        if has_grill:
            parts.append("grill")
            specs["grill"] = True
        display_bits.append("Microwave")
        if has_grill:
            display_bits.append("with Grill")

    elif typ in ("cooker", "hob"):
        burners = pieces.get("burners")
        fuel = _norm(pieces.get("fuel"))
        if fuel not in _COOKING_FUELS:
            fuel = None
        if not burners:
            return ParsedTitle()
        parts.append(f"{int(burners)}-burner")
        if fuel:
            parts.append(fuel)
        specs["burners"] = int(burners)
        if fuel:
            specs["fuel"] = fuel.title()
        display_bits += [f"{int(burners)}-Burner"]
        if fuel:
            display_bits.append(fuel.title())
        display_bits.append(typ.title())

    elif typ == "oven":
        capacity = pieces.get("capacity_liters")
        fuel = _norm(pieces.get("fuel"))
        if fuel not in _COOKING_FUELS:
            fuel = None
        if not capacity:
            return ParsedTitle()
        parts.append(f"{int(capacity)}l")
        if fuel:
            parts.append(fuel)
        specs["capacity_liters"] = int(capacity)
        if fuel:
            specs["fuel"] = fuel.title()
        display_bits += [f"{int(capacity)}L", "Oven"]

    elif typ == "hot-plate":
        burners = pieces.get("burners")
        watts = pieces.get("watts")
        if burners:
            parts.append(f"{int(burners)}-burner")
            specs["burners"] = int(burners)
        if watts:
            parts.append(f"{int(watts)}w")
            specs["watts"] = int(watts)
        display_bits += ["Hot Plate"]
        if watts:
            display_bits.append(f"({int(watts)}W)")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


# ---------------------------------------------------------------------------
# Audio (matching/audio.py)
# key: brand|type[|model_code_or_channels][|wireless/wired][|condition-if-not-new]
# ---------------------------------------------------------------------------

_AUDIO_TYPES = {
    "soundbar",
    "home-theatre",
    "party-speaker",
    "speaker",
    "earbuds",
    "headphones",
    "mp3-player",
}


def compose_audio(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    typ = _norm(pieces.get("type"))
    if not (brand and typ in _AUDIO_TYPES):
        return ParsedTitle()

    condition = _norm(pieces.get("condition")) or "new"
    specs: dict = {"type": typ.replace("-", " ").title(), "condition": condition}
    parts = [slugify(brand), typ]
    display_bits = [brand.replace("-", " ").title()]

    model_code = _norm(pieces.get("model_code"))
    channels = _norm(pieces.get("channels"))
    watts = pieces.get("watts")

    if typ in ("soundbar", "home-theatre", "party-speaker", "speaker"):
        if model_code:
            # Normalise the same way matching/audio.py does — strip ALL
            # separator chars so "SRS-XB13" and "srsxb13" produce the same
            # canonical fragment. Regex output does this via
            # `code.replace(" ","").replace("-","")` after brand-strip;
            # mirror it here so the LLM path can't drift.
            parts.append(
                model_code.replace(" ", "").replace("-", "").replace("/", "")
            )
            specs["model_code"] = model_code.upper()
        elif channels:
            parts.append(channels)
        if channels:
            specs["channels"] = channels
        if watts:
            specs["watts"] = int(watts)
        display_bits.append(typ.replace("-", " ").title())
        if model_code:
            display_bits.append(model_code.upper())
        if channels:
            display_bits.append(f"{channels}CH")
        if watts:
            display_bits.append(f"{int(watts)}W")

    elif typ in ("earbuds", "headphones"):
        wireless = bool(pieces.get("wireless"))
        if model_code:
            # Normalise the same way matching/audio.py does — strip ALL
            # separator chars so "SRS-XB13" and "srsxb13" produce the same
            # canonical fragment. Regex output does this via
            # `code.replace(" ","").replace("-","")` after brand-strip;
            # mirror it here so the LLM path can't drift.
            parts.append(
                model_code.replace(" ", "").replace("-", "").replace("/", "")
            )
            specs["model_code"] = model_code.upper()
        parts.append("wireless" if wireless else "wired")
        specs["connectivity"] = "Wireless" if wireless else "Wired"
        display_bits.append(typ.title())
        display_bits.append(specs["connectivity"])

    elif typ == "mp3-player":
        if model_code:
            # Normalise the same way matching/audio.py does — strip ALL
            # separator chars so "SRS-XB13" and "srsxb13" produce the same
            # canonical fragment. Regex output does this via
            # `code.replace(" ","").replace("-","")` after brand-strip;
            # mirror it here so the LLM path can't drift.
            parts.append(
                model_code.replace(" ", "").replace("-", "").replace("/", "")
            )
            specs["model_code"] = model_code.upper()
        display_bits.append("MP3 Player")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


# ---------------------------------------------------------------------------
# Cameras (matching/camera.py)
# key: <brand or "generic">|type|<model_code | resolution + megapixels>[|condition]
# ---------------------------------------------------------------------------

_CAMERA_TYPES = {
    "action-cam",
    "security-cam",
    "instant-camera",
    "drone-camera",
    "kids-camera",
    "mirrorless",
    "dslr",
    "digital-camera",
}


def compose_cameras(pieces: dict) -> ParsedTitle:
    typ = _norm(pieces.get("type"))
    if typ not in _CAMERA_TYPES:
        return ParsedTitle()

    brand = _norm(pieces.get("brand"))
    model_code = _norm(pieces.get("model_code"))
    megapixels = pieces.get("megapixels")
    zoom = pieces.get("zoom")
    resolution = _norm(pieces.get("resolution"))
    condition = _norm(pieces.get("condition")) or "new"

    if not (brand or model_code or resolution or megapixels):
        return ParsedTitle()

    brand_slug = slugify(brand) if brand else "generic"
    parts = [brand_slug, typ]
    if model_code:
        parts.append(model_code.replace(" ", "-"))
    else:
        if resolution:
            parts.append(resolution)
        if megapixels:
            parts.append(f"{int(megapixels)}mp")

    if condition != "new":
        parts.append(condition)

    specs: dict = {"type": typ.replace("-", " ").title(), "condition": condition}
    if model_code:
        specs["model_code"] = model_code.upper()
    if megapixels:
        specs["megapixels"] = int(megapixels)
    if zoom:
        specs["zoom"] = f"{int(zoom)}X"
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
        display_bits.append(f"{int(megapixels)}MP")
    if condition != "new":
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


# ---------------------------------------------------------------------------
# Small appliances: blenders / toasters / kettles / ironing-laundry
# (matching/small_appliances.py)
# ---------------------------------------------------------------------------

_BLENDER_SUBTYPES = {"juicer", "food-processor", "immersion", "personal", "jug"}
_TOASTER_SUBTYPES = {"pop-up", "oven"}
_KETTLE_MATERIALS = {"glass", "stainless", "plastic"}
_IRON_SUBTYPES = {"steam", "dry", "garment-steamer", "press"}


def _compose_small_common_head(pieces: dict, expected: str) -> tuple[str, str, dict, list[str]]:
    brand = _norm(pieces.get("brand"))
    if not brand:
        raise ValueError("brand required")
    condition = _norm(pieces.get("condition")) or "new"
    specs: dict = {"type": expected.title(), "condition": condition}
    parts = [slugify(brand), expected]
    return brand, condition, specs, parts


def compose_blenders(pieces: dict) -> ParsedTitle:
    if not _norm(pieces.get("brand")):
        return ParsedTitle()
    brand, condition, specs, parts = _compose_small_common_head(pieces, "blender")
    display_bits = [brand.replace("-", " ").title()]

    subtype = _norm(pieces.get("subtype"))
    if subtype not in _BLENDER_SUBTYPES:
        subtype = None
    capacity = pieces.get("capacity_liters")
    watts = pieces.get("watts")

    if subtype:
        parts.append(subtype)
        specs["subtype"] = subtype.replace("-", " ").title()
    if capacity:
        parts.append(f"{_fmt_capacity(float(capacity))}l")
        specs["capacity_liters"] = float(capacity)
    if watts:
        specs["watts"] = int(watts)

    display_bits.append((subtype or "Blender").replace("-", " ").title())
    if capacity:
        display_bits.append(f"{_fmt_capacity(float(capacity))}L")
    if watts:
        display_bits.append(f"({int(watts)}W)")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


def compose_toasters(pieces: dict) -> ParsedTitle:
    if not _norm(pieces.get("brand")):
        return ParsedTitle()
    brand, condition, specs, parts = _compose_small_common_head(pieces, "toaster")
    display_bits = [brand.replace("-", " ").title()]

    subtype = _norm(pieces.get("subtype"))
    if subtype not in _TOASTER_SUBTYPES:
        subtype = None
    slots = pieces.get("slots")
    capacity = pieces.get("capacity_liters")
    watts = pieces.get("watts")

    is_oven = subtype == "oven"
    if is_oven:
        parts.append("oven")
        specs["subtype"] = "Toaster Oven"
        if capacity:
            parts.append(f"{_fmt_capacity(float(capacity))}l")
            specs["capacity_liters"] = float(capacity)
    elif slots:
        parts.append(f"{int(slots)}-slot")
        specs["slots"] = int(slots)
    if watts:
        specs["watts"] = int(watts)

    display_bits.append("Toaster Oven" if is_oven else "Toaster")
    if slots and not is_oven:
        display_bits.append(f"{int(slots)}-Slot")
    if capacity and is_oven:
        display_bits.append(f"{_fmt_capacity(float(capacity))}L")
    if watts:
        display_bits.append(f"({int(watts)}W)")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


def compose_kettles(pieces: dict) -> ParsedTitle:
    if not _norm(pieces.get("brand")):
        return ParsedTitle()
    brand, condition, specs, parts = _compose_small_common_head(pieces, "kettle")
    display_bits = [brand.replace("-", " ").title()]

    capacity = pieces.get("capacity_liters")
    material = _norm(pieces.get("material"))
    if material not in _KETTLE_MATERIALS:
        material = None
    watts = pieces.get("watts")

    if capacity:
        parts.append(f"{_fmt_capacity(float(capacity))}l")
        specs["capacity_liters"] = float(capacity)
    if material:
        parts.append(material)
        specs["material"] = material.title()
    if watts:
        specs["watts"] = int(watts)

    display_bits.append("Kettle")
    if capacity:
        display_bits.append(f"{_fmt_capacity(float(capacity))}L")
    if material:
        display_bits.append(material.title())
    if watts:
        display_bits.append(f"({int(watts)}W)")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


def compose_ironing_laundry(pieces: dict) -> ParsedTitle:
    if not _norm(pieces.get("brand")):
        return ParsedTitle()
    brand, condition, specs, parts = _compose_small_common_head(pieces, "iron")
    display_bits = [brand.replace("-", " ").title()]

    iron_type = _norm(pieces.get("iron_type"))
    if iron_type not in _IRON_SUBTYPES:
        iron_type = "dry"
    watts = pieces.get("watts")

    parts.append(iron_type)
    specs["subtype"] = iron_type.replace("-", " ").title()
    if watts:
        specs["watts"] = int(watts)

    display_bits.append(f"{iron_type.replace('-', ' ').title()} Iron")
    if watts:
        display_bits.append(f"({int(watts)}W)")

    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


# ---------------------------------------------------------------------------
# Solar / power backup (matching/solar_energy.py)
# ---------------------------------------------------------------------------

_INVERTER_TOPOLOGIES = {"hybrid", "pure-sine", "modified", "off-grid", "grid-tie"}
_PANEL_CELL_TYPES = {"mono", "poly", "bifacial", "thin-film"}
_BATTERY_CHEMISTRIES = {"lifepo4", "lithium", "gel", "agm", "vrla", "tubular", "lead-acid"}


def compose_inverters(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    watts = pieces.get("watts")
    if not (brand and watts):
        return ParsedTitle()

    topology = _norm(pieces.get("topology"))
    if topology not in _INVERTER_TOPOLOGIES:
        topology = None
    voltage = pieces.get("system_voltage_v") or pieces.get("voltage")
    condition = _norm(pieces.get("condition")) or "new"

    parts = [slugify(brand), f"{int(watts)}w"]
    specs: dict = {"watts": int(watts), "condition": condition}
    if topology:
        parts.append(topology)
        specs["topology"] = topology.replace("-", " ").title()
    if voltage:
        specs["system_voltage_v"] = int(voltage)
    if condition != "new":
        parts.append(condition)

    display_bits = [brand.replace("-", " ").title(), f"{int(watts)}W"]
    if topology:
        display_bits.append(topology.replace("-", " ").title())
    display_bits.append("Inverter")
    if voltage:
        display_bits.append(f"({int(voltage)}V)")
    if condition != "new":
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


def compose_solar_panels(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    watts = pieces.get("watts")
    if not (brand and watts):
        return ParsedTitle()

    cell = _norm(pieces.get("cell_type"))
    if cell not in _PANEL_CELL_TYPES:
        cell = None
    condition = _norm(pieces.get("condition")) or "new"

    parts = [slugify(brand), f"{int(watts)}w"]
    specs: dict = {"watts": int(watts), "condition": condition}
    if cell:
        parts.append(cell)
        specs["cell_type"] = cell.title()
    if condition != "new":
        parts.append(condition)

    display_bits = [brand.replace("-", " ").title(), f"{int(watts)}W"]
    if cell:
        display_bits.append(cell.title())
    display_bits.append("Solar Panel")
    if condition != "new":
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


def compose_solar_batteries(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    ah = pieces.get("capacity_ah") or pieces.get("ah")
    chemistry = _norm(pieces.get("chemistry"))
    if chemistry not in _BATTERY_CHEMISTRIES:
        chemistry = None
    if not brand or not (ah or chemistry):
        return ParsedTitle()

    voltage = pieces.get("voltage_v") or pieces.get("voltage")
    condition = _norm(pieces.get("condition")) or "new"

    parts = [slugify(brand)]
    specs: dict = {"condition": condition}
    if ah:
        parts.append(f"{int(ah)}ah")
        specs["capacity_ah"] = int(ah)
    if chemistry:
        parts.append(chemistry)
        specs["chemistry"] = chemistry.replace("-", " ").upper()
    if voltage:
        parts.append(f"{int(voltage)}v")
        specs["voltage_v"] = int(voltage)
    if condition != "new":
        parts.append(condition)

    display_bits = [brand.replace("-", " ").title(), "Solar Battery"]
    if ah:
        display_bits.append(f"{int(ah)}Ah")
    if chemistry:
        display_bits.append(chemistry.replace("-", " ").upper())
    if voltage:
        display_bits.append(f"({int(voltage)}V)")
    if condition != "new":
        display_bits.append(condition.title())

    return ParsedTitle(
        brand=brand,
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


# ---------------------------------------------------------------------------
# Accessories: phone-tablet / peripherals / console (matching/accessories.py)
# The regex parser dispatches by detected type; the LLM extractor emits the
# type directly, so we take a `detected_type` and follow the same key rules.
# ---------------------------------------------------------------------------

_ACC_ACCEPTED = {
    "phone-tablet-accessories": {
        "power-bank",
        "wireless-charger",
        "car-charger",
        "charger",
        "cable",
        "screen-protector",
        "case",
        "earbuds",
        "smartwatch",
        "stylus",
    },
    "peripherals-accessories": {
        "keyboard",
        "mouse",
        "usb-hub",
        "webcam",
        "headset",
        "cable",
        "charger",
    },
    "console-accessories": {
        "controller",
        "gaming-headset",
        "charging-dock",
        "headset",
    },
}


def _compose_accessory(pieces: dict, leaf: str) -> ParsedTitle:
    accepted = _ACC_ACCEPTED[leaf]
    brand = _norm(pieces.get("brand"))
    detected = _norm(pieces.get("detected_type"))
    if not (brand and detected in accepted):
        return ParsedTitle()

    specs: dict = {"type": detected.replace("-", " ").title()}
    parts = [slugify(brand), detected]
    display_bits = [brand.replace("-", " ").title()]

    model = _norm(pieces.get("model"))
    watts = pieces.get("watts")
    mah = pieces.get("mah") or pieces.get("capacity_mah")
    connectors = _norm(pieces.get("connectors"))
    variant = _norm(pieces.get("variant"))
    generation = _norm(pieces.get("generation"))

    if detected == "power-bank":
        if not mah:
            return ParsedTitle()
        parts.append(f"{int(mah)}mah")
        specs["capacity_mah"] = int(mah)
        display_bits.append(f"{int(mah)}mAh Power Bank")
        if watts:
            specs["watts"] = int(watts)
            display_bits.append(f"({int(watts)}W)")

    elif detected in ("charger", "wireless-charger", "car-charger"):
        if not (watts or model):
            return ParsedTitle()
        if model:
            parts.append(slugify(model))
            specs["model"] = model.upper()
        if watts:
            parts.append(f"{int(watts)}w")
            specs["watts"] = int(watts)
        pretty_type = detected.replace("-", " ").title()
        display_bits.append(pretty_type)
        if watts:
            display_bits.append(f"({int(watts)}W)")
        if model:
            display_bits.append(model.upper())

    elif detected == "cable":
        if not connectors:
            return ParsedTitle()
        parts.append(connectors)
        specs["connectors"] = connectors.replace("-", " → ").upper()
        display_bits.append(f"{connectors.upper().replace('-', ' → ')} Cable")

    elif detected == "smartwatch":
        if brand == "apple":
            if not variant:
                return ParsedTitle()
            parts.append(variant)
            specs["variant"] = variant.replace("-", " ").title()
            display_bits.append(f"Watch {variant.replace('-', ' ').title()}")
        elif brand == "samsung":
            if not variant:
                return ParsedTitle()
            parts.append(variant)
            specs["variant"] = f"Galaxy Watch {variant.title()}"
            display_bits.append(f"Galaxy Watch {variant.title()}")
        else:
            if not model:
                return ParsedTitle()
            parts.append(slugify(model))
            specs["model"] = model.upper()
            display_bits.append(f"Smartwatch {model.upper()}")

    elif detected == "stylus":
        if brand == "apple":
            if not generation:
                return ParsedTitle()
            parts.append(generation)
            specs["generation"] = generation.replace("-", " ").title()
            display_bits.append(f"Pencil ({generation.replace('-', ' ').title()})")
        elif brand == "samsung":
            display_bits.append("S Pen")
        else:
            if not model:
                return ParsedTitle()
            parts.append(slugify(model))
            specs["model"] = model.upper()
            display_bits.append(f"Stylus {model.upper()}")

    elif detected == "earbuds":
        if not model:
            return ParsedTitle()
        parts.append(slugify(model))
        specs["model"] = model.replace("-", " ").title()
        display_bits.append(model.replace("-", " ").title())

    elif detected == "controller":
        if not (variant or model):
            return ParsedTitle()
        picked = variant or model
        parts.append(slugify(picked))
        specs["model"] = picked.replace("-", " ").title() if variant else picked.upper()
        display_bits.append(specs["model"] + " Controller")

    elif detected == "gaming-headset":
        if not (variant or model):
            return ParsedTitle()
        picked = variant or model
        parts.append(slugify(picked))
        specs["model"] = picked.replace("-", " ").title() if variant else picked.upper()
        display_bits.append(specs["model"] + " Headset")

    elif detected in (
        "headset",
        "keyboard",
        "mouse",
        "webcam",
        "usb-hub",
        "charging-dock",
        "screen-protector",
        "case",
    ):
        if not model:
            return ParsedTitle()
        parts.append(slugify(model))
        specs["model"] = model.upper()
        pretty_type = detected.replace("-", " ").title()
        display_bits.append(f"{pretty_type} {model.upper()}")

    return ParsedTitle(
        brand=brand,
        model=specs.get("model") if isinstance(specs.get("model"), str) else None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(x for x in display_bits if x).strip(),
    )


def compose_phone_tablet_accessories(pieces: dict) -> ParsedTitle:
    return _compose_accessory(pieces, "phone-tablet-accessories")


def compose_peripherals_accessories(pieces: dict) -> ParsedTitle:
    return _compose_accessory(pieces, "peripherals-accessories")


def compose_console_accessories(pieces: dict) -> ParsedTitle:
    return _compose_accessory(pieces, "console-accessories")


# ---------------------------------------------------------------------------
# Consoles: PlayStation 5 / Xbox Series / Nintendo Switch (matching/consoles.py)
# ---------------------------------------------------------------------------

_PS5_REVISIONS = {"standard", "slim", "pro"}
_PS5_EDITIONS = {"disc", "digital"}
_CONSOLE_STORAGE = {"512gb", "825gb", "1tb", "2tb", "4tb"}
_XBOX_FAMILIES = {"xbox-series-x", "xbox-series-s"}
_SWITCH_FAMILIES = {"switch", "switch-2", "switch-lite", "switch-oled"}


def _norm_storage(value: Any) -> str | None:
    """Normalise LLM-emitted storage strings ("1 TB", "825 GB") to the same
    token the regex parser produces ("1tb", "825gb")."""
    s = _norm(value)
    if not s:
        return None
    s = s.replace(" ", "")
    return s if s in _CONSOLE_STORAGE else None


def compose_playstation_5(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    if brand not in ("sony", "playstation"):
        return ParsedTitle()
    revision = _norm(pieces.get("revision")) or "standard"
    if revision not in _PS5_REVISIONS:
        return ParsedTitle()
    edition = _norm(pieces.get("edition"))
    if edition and edition not in _PS5_EDITIONS:
        edition = None
    storage = _norm_storage(pieces.get("storage"))
    condition = _norm(pieces.get("condition")) or "new"

    parts = ["sony", "ps5", revision]
    specs: dict = {"condition": condition, "revision": revision.title()}
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
    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand="sony",
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


def compose_xbox_series(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    if brand not in ("microsoft", "xbox"):
        return ParsedTitle()
    family = _norm(pieces.get("family"))
    if family not in _XBOX_FAMILIES:
        return ParsedTitle()
    storage = _norm_storage(pieces.get("storage"))
    condition = _norm(pieces.get("condition")) or "new"

    parts = ["microsoft", family]
    family_display = family.replace("-", " ").title()
    specs: dict = {"condition": condition, "family": family_display}
    display_bits = ["Microsoft", family_display]
    if storage:
        parts.append(storage)
        specs["storage"] = storage.upper()
        display_bits.append(storage.upper())
    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand="microsoft",
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


def compose_nintendo_switch(pieces: dict) -> ParsedTitle:
    brand = _norm(pieces.get("brand"))
    if brand not in ("nintendo",):
        return ParsedTitle()
    family = _norm(pieces.get("family"))
    if family not in _SWITCH_FAMILIES:
        return ParsedTitle()
    condition = _norm(pieces.get("condition")) or "new"

    parts = ["nintendo", family]
    family_display = family.replace("-", " ").title()
    specs: dict = {"condition": condition, "family": family_display}
    display_bits = ["Nintendo", family_display]
    if condition != "new":
        parts.append(condition)
        display_bits.append(condition.title())

    return ParsedTitle(
        brand="nintendo",
        model=None,
        canonical_key="|".join(parts),
        specs=specs,
        display_title=" ".join(display_bits).strip(),
    )


# ---------------------------------------------------------------------------
# Public registry — slug → composer
# ---------------------------------------------------------------------------


COMPOSERS: dict[str, Any] = {
    "phones": compose_phones,
    "tablets": compose_tablets,
    "laptops": compose_laptops,
    "tvs": compose_tvs,
    "refrigerators": compose_refrigerators,
    "freezers": compose_freezers,
    "water-dispensers": compose_water_dispensers,
    "washers-dryers": compose_washers_dryers,
    "cooking": compose_cooking,
    "audio": compose_audio,
    "cameras": compose_cameras,
    "blenders": compose_blenders,
    "toasters": compose_toasters,
    "kettles": compose_kettles,
    "ironing-laundry": compose_ironing_laundry,
    "inverters": compose_inverters,
    "solar-panels": compose_solar_panels,
    "solar-batteries": compose_solar_batteries,
    "phone-tablet-accessories": compose_phone_tablet_accessories,
    "peripherals-accessories": compose_peripherals_accessories,
    "console-accessories": compose_console_accessories,
    "playstation-5": compose_playstation_5,
    "xbox-series": compose_xbox_series,
    "nintendo-switch": compose_nintendo_switch,
}
