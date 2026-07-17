"""Parity guard: the LLM-path composers in matching/compose_keys.py MUST
produce the same canonical_key as each category's regex parser for
titles the regex successfully parses.

If a regex parser adds a spec that participates in its key (or renames an
enum value like `pure sine` → `pure-sine`), the corresponding composer here
must be updated to match — or LLM-parsed and regex-parsed products will
create two Product rows instead of one.

We don't cover every parser branch; the fixtures below hand-craft (pieces,
expected_key) tuples that mirror what the LLM would emit for a known-good
title. That's enough to catch structural drift.
"""

from __future__ import annotations

import pytest

from matching import compose_keys


@pytest.mark.parametrize(
    "slug,pieces,expected_key",
    [
        (
            "phones",
            {"brand": "tecno", "model": "spark 30c", "storage_gb": 256, "ram_gb": 8},
            "tecno|spark-30c|256|8",
        ),
        (
            "phones",
            {"brand": "apple", "model": "iphone 15", "storage_gb": 128},
            "apple|iphone-15|128",
        ),
        (
            "tablets",
            {"brand": "samsung", "model": "tab s9", "screen_inches": 11, "storage_gb": 128, "ram_gb": 8},
            "samsung|tab-s9|11in|128|8",
        ),
        (
            "laptops",
            {
                "brand": "hp",
                "model_line": "elitebook",
                "variant": "840 g3",
                "cpu_family": "i5",
                "cpu_gen": 6,
                "ram_gb": 8,
                "storage_gb": 256,
                "storage_type": "ssd",
                "condition": "refurbished",
            },
            "hp|elitebook-840-g3|i5-6|8|256-ssd|refurbished",
        ),
        (
            "tvs",
            {
                "brand": "samsung",
                "size_inches": 55,
                "resolution": "4k",
                "panel": "qled",
                "smart": True,
            },
            "samsung|55|4k|qled|smart",
        ),
        (
            "tvs",
            {"brand": "vision-plus", "size_inches": 32, "smart": False},
            "vision-plus|32|basic",
        ),
        (
            "refrigerators",
            {"brand": "hisense", "capacity_liters": 138, "door_type": "single"},
            "hisense|138l|single",
        ),
        (
            "freezers",
            {"brand": "bruhm", "capacity_liters": 300, "freezer_type": "chest"},
            "bruhm|300l|chest",
        ),
        (
            "water-dispensers",
            {"brand": "ramtons", "model": "rm/577", "dispenser_type": "hot-cold"},
            "ramtons|rm-577|hot-cold",
        ),
        (
            "washers-dryers",
            {
                "brand": "hisense",
                "capacity_kg": 8,
                "load_type": "front",
                "automation": "auto",
            },
            "hisense|8kg|front|auto",
        ),
        (
            "washers-dryers",
            {"brand": "bruhm", "capacity_kg": 10, "load_type": "twin-tub"},
            "bruhm|10kg|twin-tub|semi-auto",
        ),
        (
            "cooking",
            {
                "brand": "ramtons",
                "type": "microwave",
                "capacity_liters": 20,
                "control": "digital",
                "has_grill": True,
            },
            "ramtons|microwave|20l|digital|grill",
        ),
        (
            "cooking",
            {"brand": "mika", "type": "cooker", "burners": 4, "fuel": "gas"},
            "mika|cooker|4-burner|gas",
        ),
        (
            "audio",
            {
                "brand": "lyons",
                "type": "home-theatre",
                "model_code": "lys3602",
                "channels": "2.1",
            },
            "lyons|home-theatre|lys3602",
        ),
        (
            "audio",
            {"brand": "oraimo", "type": "earbuds", "model_code": "otw-100", "wireless": True},
            # Hyphens stripped to match matching/audio.py::_find_model_code
            # normalisation. Same product across two merchants (one titled
            # "OTW-100", another "OTW100") lands under the same canonical key.
            "oraimo|earbuds|otw100|wireless",
        ),
        (
            "cameras",
            {"brand": "hikvision", "type": "security-cam", "model_code": "dc226"},
            "hikvision|security-cam|dc226",
        ),
        (
            "cameras",
            {"type": "action-cam", "megapixels": 20, "resolution": "4k"},
            "generic|action-cam|4k|20mp",
        ),
        (
            "blenders",
            {
                "brand": "ramtons",
                "subtype": "jug",
                "capacity_liters": 1.5,
                "watts": 500,
            },
            "ramtons|blender|jug|1.5l",
        ),
        (
            "toasters",
            {"brand": "mika", "subtype": "pop-up", "slots": 2, "watts": 800},
            "mika|toaster|2-slot",
        ),
        (
            "kettles",
            {"brand": "ramtons", "capacity_liters": 1.7, "material": "stainless"},
            "ramtons|kettle|1.7l|stainless",
        ),
        (
            "ironing-laundry",
            {"brand": "philips", "iron_type": "steam", "watts": 2400},
            "philips|iron|steam",
        ),
        (
            "inverters",
            {"brand": "growatt", "watts": 3000, "topology": "hybrid", "voltage": 24},
            "growatt|3000w|hybrid",
        ),
        (
            "solar-panels",
            {"brand": "solarmax", "watts": 400, "cell_type": "mono"},
            "solarmax|400w|mono",
        ),
        (
            "solar-batteries",
            {"brand": "felicity", "capacity_ah": 200, "chemistry": "lifepo4", "voltage": 48},
            "felicity|200ah|lifepo4|48v",
        ),
        (
            "phone-tablet-accessories",
            {
                "brand": "anker",
                "detected_type": "power-bank",
                "mah": 20000,
                "watts": 22,
            },
            "anker|power-bank|20000mah",
        ),
        (
            "phone-tablet-accessories",
            {
                "brand": "apple",
                "detected_type": "smartwatch",
                "variant": "series-10",
            },
            "apple|smartwatch|series-10",
        ),
        (
            "peripherals-accessories",
            {
                "brand": "logitech",
                "detected_type": "mouse",
                "model": "mx3s",
            },
            "logitech|mouse|mx3s",
        ),
        (
            "console-accessories",
            {
                "brand": "microsoft",
                "detected_type": "controller",
                "variant": "xbox-elite-2",
            },
            "microsoft|controller|xbox-elite-2",
        ),
        (
            "playstation-5",
            {
                "brand": "sony",
                "revision": "slim",
                "edition": "disc",
                "storage": "1TB",
            },
            "sony|ps5|slim|disc|1tb",
        ),
        (
            "xbox-series",
            {"brand": "microsoft", "family": "xbox-series-x", "storage": "2TB"},
            "microsoft|xbox-series-x|2tb",
        ),
        (
            "nintendo-switch",
            {"brand": "nintendo", "family": "switch-oled"},
            "nintendo|switch-oled",
        ),
    ],
)
def test_composer_key_shapes(slug: str, pieces: dict, expected_key: str) -> None:
    composer = compose_keys.COMPOSERS[slug]
    parsed = composer(pieces)
    assert parsed.canonical_key == expected_key, (
        f"{slug} composer produced {parsed.canonical_key!r}; "
        f"expected {expected_key!r}"
    )


def test_all_slugs_have_composer() -> None:
    """Every category slug in matching/normalize._PARSERS + the two orphan
    slugs (freezers, water-dispensers) MUST have a composer registered.
    Otherwise the LLM fallback silently no-ops for that category."""
    from matching.normalize import _PARSERS

    orphan_slugs = {"freezers", "water-dispensers"}
    for slug in _PARSERS:
        assert slug in compose_keys.COMPOSERS, f"missing composer for {slug}"
    for slug in orphan_slugs:
        assert slug in compose_keys.COMPOSERS, f"missing composer for orphan slug {slug}"


def test_phone_composer_applies_brand_aliases() -> None:
    """LLM sometimes returns `brand="iphone"` (from the literal token in the
    title) where the phone regex parser applies BRAND_ALIASES and lands on
    `brand="apple"`. Without alias handling in compose_phones, two listings
    for the same iPhone SKU can split — one keyed `apple|iphone-14|256|6`
    (regex), the other `iphone|14|256|6` (LLM). Real drift observed on
    2026-07-14 during LLM-fallback smoke testing.
    """
    from matching import compose_keys
    parsed = compose_keys.compose_phones(
        {"brand": "iphone", "model": "iphone 14", "storage_gb": 256, "ram_gb": 6}
    )
    assert parsed.canonical_key == "apple|iphone-14|256|6"
    # `redmi` and `pixel` are the other two aliases in the regex parser.
    parsed_redmi = compose_keys.compose_phones(
        {"brand": "redmi", "model": "note 13 pro", "storage_gb": 256, "ram_gb": 8}
    )
    assert parsed_redmi.canonical_key == "xiaomi|note-13-pro|256|8"
    parsed_pixel = compose_keys.compose_phones(
        {"brand": "pixel", "model": "pixel 8 pro", "storage_gb": 128}
    )
    assert parsed_pixel.canonical_key == "google|pixel-8-pro|128"


def test_audio_composer_normalises_hyphens_in_model_code() -> None:
    """Audio regex parser strips ALL hyphens/spaces when normalising a model
    code — Sony `SRS-XB13` becomes `srsxb13`, LG `HW-Q800D` becomes `hwq800d`.
    LLM-emitted `model_code="SRS-XB13"` must produce the same normalised
    fragment or two listings for the same speaker land under different keys.
    Real drift observed on 2026-07-14 during LLM smoke testing.
    """
    from matching import compose_keys
    parsed = compose_keys.compose_audio(
        {"brand": "sony", "type": "speaker", "model_code": "SRS-XB13"}
    )
    assert parsed.canonical_key == "sony|speaker|srsxb13"
    parsed_lg = compose_keys.compose_audio(
        {"brand": "samsung", "type": "soundbar", "model_code": "HW-Q800D"}
    )
    assert parsed_lg.canonical_key == "samsung|soundbar|hwq800d"
    # A model code with an internal space collapses too ("Bar 800MK2" ->
    # "bar800mk2" — matches the audio regex output).
    parsed_jbl = compose_keys.compose_audio(
        {"brand": "jbl", "type": "soundbar", "model_code": "Bar 800MK2"}
    )
    assert parsed_jbl.canonical_key == "jbl|soundbar|bar800mk2"


def test_composer_rejects_missing_brand() -> None:
    """No brand → unparsed. Should hold for every composer."""
    for slug, composer in compose_keys.COMPOSERS.items():
        parsed = composer({"is_valid_for_category": True})
        # Cameras allow a "generic" brand when a type + spec is present, so
        # accept either "no key" or a non-brand-specific key that's still
        # coherent. All other categories must reject.
        if slug == "cameras":
            continue
        assert parsed.canonical_key is None, (
            f"{slug} composer produced a key with no brand: {parsed.canonical_key!r}"
        )
