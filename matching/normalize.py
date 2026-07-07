"""Category-aware title-parsing dispatcher.

Callers ask parse_title(title, category="laptops") and this module routes to the
appropriate category-specific parser. Categories that don't have a parser yet
return an unparsed ParsedTitle, which the ingest pipeline silently skips.
"""

from __future__ import annotations

from collections.abc import Callable

from matching import (
    audio,
    camera,
    cooking,
    laptop,
    phone,
    refrigerator,
    small_appliances,
    solar_energy,
    tv,
    washer,
)
from matching.base import ParsedTitle

# Category slug → parser function.
# Add new category parsers as they ship. Anything not in this map yields an
# empty ParsedTitle (ingest will drop the listing until we ship a parser).
_PARSERS: dict[str, Callable[[str], ParsedTitle]] = {
    "phones": phone.parse_title,
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
}


def parse_title(title: str, category: str = "phones") -> ParsedTitle:
    parser = _PARSERS.get(category)
    if not parser:
        return ParsedTitle()
    return parser(title)


def has_parser_for(category: str) -> bool:
    return category in _PARSERS
