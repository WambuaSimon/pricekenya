"""Category-aware title-parsing dispatcher.

Callers ask parse_title(title, category="laptops") and this module routes to the
appropriate category-specific parser. Categories that don't have a parser yet
return an unparsed ParsedTitle, which the ingest pipeline silently skips.
"""

from __future__ import annotations

from collections.abc import Callable

from matching import phone
from matching.base import ParsedTitle

# Category slug → parser function.
# Add new category parsers as they ship. Anything not in this map yields an
# empty ParsedTitle (ingest will drop the listing until we ship a parser).
_PARSERS: dict[str, Callable[[str], ParsedTitle]] = {
    "phones": phone.parse_title,
}


def parse_title(title: str, category: str = "phones") -> ParsedTitle:
    parser = _PARSERS.get(category)
    if not parser:
        return ParsedTitle()
    return parser(title)


def has_parser_for(category: str) -> bool:
    return category in _PARSERS
