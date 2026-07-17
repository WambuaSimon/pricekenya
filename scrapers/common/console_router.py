"""Title-based console-leaf dispatcher.

Merchant "gaming console" category URLs and search results almost always
mix PS5 + Xbox + Switch on one page. Hard-coding such a URL to a single
console leaf (playstation-5 / xbox-series / nintendo-switch) means the
other two families' listings get rejected by the matcher and silently
drop. This helper inspects each title and returns the right leaf.

Delegates to `matching.consoles.parse_title` per family — a title
"belongs to" the first family whose matcher accepts it. That mirrors
production: whatever the ingest matcher would accept is what the router
routes there. When the matcher rejects (retro handheld, actual game,
accessory, cross-family noise), the router returns None and the caller
drops the row without an ingest round-trip.
"""

from __future__ import annotations

from matching.consoles import parse_title as _parse_console

_FAMILY_TO_LEAF: tuple[tuple[str, str], ...] = (
    ("ps5", "playstation-5"),
    ("xbox-series", "xbox-series"),
    ("switch", "nintendo-switch"),
)


def classify_console_leaf(title: str) -> str | None:
    """Return the taxonomy leaf slug for a console listing, or None if
    the title doesn't look like an actual PS5/Xbox Series/Nintendo Switch
    console (retro clone, game, accessory, unrelated device)."""
    for expected, leaf in _FAMILY_TO_LEAF:
        if _parse_console(title, expected_type=expected).canonical_key:
            return leaf
    return None
