"""Smoke tests for the title-based console-leaf dispatcher.

The router is a thin wrapper around matching.consoles.parse_title, so
these tests focus on the dispatch contract (correct leaf per family;
None for rejects) rather than re-testing the matcher's own reject rules.
"""

import pytest

from scrapers.common.console_router import classify_console_leaf


@pytest.mark.parametrize(
    "title,expected_leaf",
    [
        # PS5 family — Jumia listings
        ("Playstation ps5 Slim Disc Version 1TB", "playstation-5"),
        ("Sony Interactive Entertainment PlayStation 5 Pro Console - 2TB", "playstation-5"),
        ("Playstation Sony PS5 Standard Console – 1TB SSD (Disc Edition)", "playstation-5"),
        # Xbox family
        ("Microsoft Xbox Series X 1TB Console", "xbox-series"),
        ("XBOX Series S - 512GB SSD Console", "xbox-series"),
        # Switch family — the qualified variants (switch 2 / lite / oled)
        # are self-identifying; bare "switch" needs a console/joy-con signal.
        ("Nintendo Switch OLED Model", "nintendo-switch"),
        ("Nintendo Switch 2", "nintendo-switch"),
        ("Nintendo Switch Lite - Turquoise", "nintendo-switch"),
        ("Nintendo Switch Console With Red And Blue", "nintendo-switch"),
    ],
)
def test_dispatch(title: str, expected_leaf: str | None) -> None:
    assert classify_console_leaf(title) == expected_leaf


@pytest.mark.parametrize(
    "title",
    [
        # Retro handheld clones
        "R36S Retro Handheld Game Console Linux System, 64G",
        "M15 4K Game Stick TV Video Game Console",
        # Accessories
        "Sony DualSense Wireless Controller for PlayStation 5",
        "Xbox Wireless Controller - Carbon Black",
        # Games (leak into console category pages)
        "Sony PS5 FC26",
        "Nintendo Switch Sports",
        "The Legend of Zelda Nintendo Switch",
        # Unrelated devices
        "TP-Link 8-Port Gigabit Network Switch",
    ],
)
def test_non_console_titles_dispatch_to_none(title: str) -> None:
    assert classify_console_leaf(title) is None
