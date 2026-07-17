"""Category-aware title-parsing dispatcher.

Callers ask parse_title(title, category="laptops") and this module routes to the
appropriate category-specific parser. Categories that don't have a parser yet
return an unparsed ParsedTitle, which the ingest pipeline silently skips.
"""

from __future__ import annotations

from collections.abc import Callable

from matching import (
    accessories,
    audio,
    camera,
    coffee_machines,
    consoles,
    cooking,
    dishwashers,
    home_fixtures,
    laptop,
    phone,
    refrigerator,
    small_appliances,
    solar_energy,
    tablet,
    tv,
    washer,
)
from matching.base import ParsedTitle

# Category slug → parser function.
# Add new category parsers as they ship. Anything not in this map yields an
# empty ParsedTitle (ingest will drop the listing until we ship a parser).
_PARSERS: dict[str, Callable[[str], ParsedTitle]] = {
    "phones": phone.parse_title,
    "tablets": tablet.parse_title,
    "laptops": laptop.parse_title,
    "tvs": tv.parse_title,
    "refrigerators": refrigerator.parse_title,
    "washers-dryers": washer.parse_title,
    "cooking": cooking.parse_title,
    "audio": audio.parse_title,
    "cameras": camera.parse_title,
    # Small-appliance leaves share one matcher module with an expected-type
    # closure so a kettle in the toasters feed gets rejected.
    "blenders": lambda t: small_appliances.parse_title(t, expected_type="blender"),
    "toasters": lambda t: small_appliances.parse_title(t, expected_type="toaster"),
    "kettles": lambda t: small_appliances.parse_title(t, expected_type="kettle"),
    "ironing-laundry": lambda t: small_appliances.parse_title(t, expected_type="iron"),
    # Solar / power-backup — shared matcher module, expected_type distinguishes.
    "inverters": lambda t: solar_energy.parse_title(t, expected_type="inverter"),
    "solar-panels": lambda t: solar_energy.parse_title(t, expected_type="solar-panel"),
    "solar-batteries": lambda t: solar_energy.parse_title(t, expected_type="solar-battery"),
    # Accessories — shared matcher module; expected_category maps each leaf
    # to the type set it accepts (a gaming controller in phone-tablet-
    # accessories, or a wall charger in console-accessories, gets rejected).
    "phone-tablet-accessories": lambda t: accessories.parse_title(
        t, expected_category="phone-tablet-accessories"
    ),
    "peripherals-accessories": lambda t: accessories.parse_title(
        t, expected_category="peripherals-accessories"
    ),
    "console-accessories": lambda t: accessories.parse_title(
        t, expected_category="console-accessories"
    ),
    # Consoles — shared matcher module; expected_type keeps a PS5 SKU out of
    # the Xbox/Switch leaves. Retro-handheld noise, actual games, and
    # accessories are rejected inside the matcher.
    "playstation-5": lambda t: consoles.parse_title(t, expected_type="ps5"),
    "xbox-series": lambda t: consoles.parse_title(t, expected_type="xbox-series"),
    "nintendo-switch": lambda t: consoles.parse_title(t, expected_type="switch"),
    # Dishwashers — split from washers-dryers on 2026-07-17; different
    # spec vocabulary (place-settings, integrated vs freestanding).
    "dishwashers": dishwashers.parse_title,
    # Coffee machines — separate leaf under small-appliances so a KSh 200k
    # bean-to-cup doesn't collide-key with a KSh 5k drip.
    "coffee-machines": coffee_machines.parse_title,
    # Home & kitchen fixtures — shared matcher, expected_type dispatches
    # per leaf (sinks/taps/countertops/splashbacks/hardware/utensils/toilets).
    "kitchen-sinks-taps": lambda t: home_fixtures.parse_title(t, expected_type="kitchen-sinks-taps"),
    "countertops": lambda t: home_fixtures.parse_title(t, expected_type="countertops"),
    "splashbacks": lambda t: home_fixtures.parse_title(t, expected_type="splashbacks"),
    "kitchen-hardware": lambda t: home_fixtures.parse_title(t, expected_type="kitchen-hardware"),
    "utensils": lambda t: home_fixtures.parse_title(t, expected_type="utensils"),
    "toilets": lambda t: home_fixtures.parse_title(t, expected_type="toilets"),
}


def parse_title(
    title: str, category: str = "phones", description: str | None = None
) -> ParsedTitle:
    # Description is an optional secondary signal (used today only by the
    # phone parser to fill in storage/RAM when the title omits them). Other
    # categories accept the argument silently — most parsers derive their
    # canonical key from tokens that are almost always in the title.
    if category == "phones":
        return phone.parse_title(title, description=description)
    parser = _PARSERS.get(category)
    if not parser:
        return ParsedTitle()
    return parser(title)


def has_parser_for(category: str) -> bool:
    return category in _PARSERS
