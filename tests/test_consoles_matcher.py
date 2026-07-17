"""Regression tests for the consoles matcher.

One module handles PlayStation 5, Xbox Series X/S, and Nintendo Switch —
each dispatched via the normalize.py category map. Fixtures use real
listing titles scraped from Jumia + phoneplacekenya + phoneshopkenya.
"""

import pytest

from matching.normalize import parse_title

# ---------------------------------------------------------------------------
# PlayStation 5 — the dominant console SKU in Kenyan retail
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Jumia — Slim + Disc + 1TB, various brand-string phrasings
        ("Playstation ps5 Slim Disc Version 1TB", "sony|ps5|slim|disc|1tb"),
        ("Playstation ps5 slim disc version", "sony|ps5|slim|disc"),
        (
            "Playstation Sony PS5 Standard Console – 1TB SSD (Disc Edition)",
            "sony|ps5|standard|disc|1tb",
        ),
        # Digital Edition (no disc drive)
        (
            "Sony Computer Entertainment PlayStation®5 Digital Edition Slim – 1TB",
            "sony|ps5|slim|digital|1tb",
        ),
        ("Playstation ps5 slim digital edition", "sony|ps5|slim|digital"),
        # Pro (2TB by default)
        (
            "Sony Interactive Entertainment PlayStation 5 Pro Console - 2TB",
            "sony|ps5|pro|2tb",
        ),
        (
            "Playstation Sony Interactive Entertainment PS5 Pro Console - 2TB",
            "sony|ps5|pro|2tb",
        ),
        # Bare "PS5 Slim" (no edition spelled out)
        ("Playstation Play Station 5 Slim 1tb", "sony|ps5|slim|1tb"),
    ],
)
def test_ps5_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="playstation-5").canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        # Actual games listed on the console category page
        "Sony PS5 FC26",
        "SON FC26 PS5",
        "Rockstar Games GTA TRIOLOGY PS4 DEFINITIVE EDITION",
        "Sega Sonic superstars",
        # Retro handheld noise — sold in "gaming console" search results
        "M15 4K Game Stick TV Video Game Console Built-in 20000 Games",
        "R36S Retro Handheld Game Console Linux System, 64G - Purple",
        "R36S PS retro 3.5 inch IPS screen mini portable video handheld",
        "J36 Ultra 3.5-Inch IPS Portable Retro Game Console",
        "X80 handheld game player 7 inch large screen",
        "X18 Linux Handheld Game Console 4.3 Inch Screen",
        # Accessories in the PS5 aisle
        "Sony DualSense Wireless Controller for PlayStation 5",
        "PS5 Charging Dock Stand",
        # Cross-family (Xbox in a PS5 leaf) — reject rather than mis-key
        "Xbox Series X 1TB",
        "Nintendo Switch OLED",
    ],
)
def test_ps5_rejects(title: str) -> None:
    assert parse_title(title, category="playstation-5").canonical_key is None


# ---------------------------------------------------------------------------
# Xbox Series X / S
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        ("Microsoft Xbox Series X 1TB Console", "microsoft|xbox-series-x|1tb"),
        ("Xbox Series X 2TB Galaxy Black Special Edition", "microsoft|xbox-series-x|2tb"),
        ("Microsoft Xbox Series S 512GB Console - White", "microsoft|xbox-series-s|512gb"),
        ("Xbox Series S 1TB Black", "microsoft|xbox-series-s|1tb"),
    ],
)
def test_xbox_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="xbox-series").canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        # Accessories
        "Xbox Wireless Controller - Carbon Black",
        "Xbox Elite Series 2 Controller",
        # Games
        "GTA V Xbox Series X",
        "Call of Duty Modern Warfare III Xbox Series X",
        # Cross-family
        "Sony PlayStation 5 Slim 1TB",
        "Nintendo Switch OLED",
        # Retro clone
        "Handheld Game Console 64GB 15000 games",
        # Xbox 360 (legacy — not the Series family we key)
        "Xbox 360 Slim 250GB",
    ],
)
def test_xbox_rejects(title: str) -> None:
    assert parse_title(title, category="xbox-series").canonical_key is None


# ---------------------------------------------------------------------------
# Nintendo Switch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Jumia — the newest Switch 2
        ("Nintendo Switch Switch 2 hand held gaming console", "nintendo|switch-2"),
        # Standard Switch
        ("Nintendo Switch Console - Grey Joy-Con", "nintendo|switch"),
        # Bare "Switch OLED" — self-identifying, doesn't need "Nintendo" nearby
        ("Switch OLED Model 64GB White", "nintendo|switch-oled"),
        ("Nintendo Switch OLED Neon Red/Blue", "nintendo|switch-oled"),
        # Lite
        ("Nintendo Switch Lite Coral", "nintendo|switch-lite"),
    ],
)
def test_switch_titles(title: str, expected_key: str) -> None:
    assert parse_title(title, category="nintendo-switch").canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        # Bare "switch" without Nintendo or console context — network switch,
        # not the Nintendo one.
        "TP-Link 8-Port Gigabit Network Switch",
        "Cisco Catalyst 2960 Switch",
        # Accessories
        "Nintendo Switch Pro Controller",
        "Switch Joy-Con Charging Dock",
        "Nintendo Switch Carrying Case",
        # Games
        "Nintendo Switch Sports",
        "The Legend of Zelda Nintendo Switch",
        # Cross-family
        "Sony PlayStation 5 Slim",
        "Xbox Series X",
    ],
)
def test_switch_rejects(title: str) -> None:
    assert parse_title(title, category="nintendo-switch").canonical_key is None


# ---------------------------------------------------------------------------
# Cross-leaf integration: same title routed to the wrong leaf drops.
# ---------------------------------------------------------------------------

def test_ps5_title_routed_to_xbox_drops() -> None:
    title = "Sony PlayStation 5 Slim 1TB Disc Edition"
    assert parse_title(title, category="playstation-5").canonical_key
    assert parse_title(title, category="xbox-series").canonical_key is None
    assert parse_title(title, category="nintendo-switch").canonical_key is None


def test_condition_applied_to_key() -> None:
    used = parse_title(
        "Used PS5 Slim 1TB Disc Version", category="playstation-5"
    )
    assert used.canonical_key == "sony|ps5|slim|disc|1tb|used"

    refurb = parse_title(
        "Refurbished Xbox Series X 1TB", category="xbox-series"
    )
    assert refurb.canonical_key == "microsoft|xbox-series-x|1tb|refurbished"
