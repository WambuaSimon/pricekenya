"""Regression tests for the audio matcher.

Kenyan retail audio is dominated by home-theatre / subwoofer systems (Lyons,
AILYONS, Vitron, Amtec) alongside branded consumer audio (JBL, Sony, Oraimo).
These tests lock in the essential behaviours: model codes as canonical
differentiators, watts filtering (Kenyan retail lists 9000W speakers), and
robust rejection of chargers and cables that leak into the audio feed.
"""

import pytest

from matching.normalize import parse_title


@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Home theatres — model code drives the canonical key so same brand +
        # same channel doesn't merge distinct SKUs
        (
            "Lyons LYS3602 3.1CH Multimedia Speaker System Home Theatre",
            "lyons|home-theatre|lys3602",
        ),
        (
            "AILYONS ELP2406K 2.1CH Subwoofer Home Theatre",
            "ailyons|home-theatre|elp2406k",
        ),
        # Soundbars
        ("Hisense Soundbar 540 Watts 5.1 Channel HS5100", "hisense|soundbar|hs5100"),
        (
            "Vision Plus VP2121SB Sound Pro 450W 2.1 CH Subwoofer Sound Bar",
            "vision-plus|soundbar|vp2121sb",
        ),
        # Branded earbuds / headphones — wireless flag captured
        ("JBL Tune 510BT Wireless On-Ear Headphones", "jbl|headphones|tune510bt|wireless"),
        ("Oraimo FreePods 3 True Wireless Earbuds", "oraimo|earbuds|wireless"),
    ],
)
def test_audio_titles(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="audio")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Samsung 45W USB-C Fast Charger Adapter Wall Plug",
        "2 In1 USB Wireless Bluetooth Adapter 5.0 Transmitter",
        "HDMI Cable 2 Meters 4K",
        "Universal Speaker Bracket Wall Mount",
        "Ear Cushion Replacement for Sony Headphones",
    ],
)
def test_non_audio_items_rejected(title: str) -> None:
    parsed = parse_title(title, category="audio")
    assert parsed.canonical_key is None


def test_same_brand_channel_different_model_do_not_merge() -> None:
    """The three Lyons 3.1CH SKUs are separate products; the model code must
    keep them apart in the canonical key."""
    keys = {
        parse_title(t, category="audio").canonical_key
        for t in [
            "Lyons LYS3602 3.1CH Multimedia Speaker System Home Theatre",
            "Lyons LYS3604 3.1CH Multimedia Speaker System Home Theatre",
            "Lyons LYS3605 3.1CH Multimedia Speaker System Home Theatre",
        ]
    }
    assert len(keys) == 3


def test_inflated_wattage_kept_out_of_canonical_key() -> None:
    """Kenyan retail claims 9000W and 20000W speakers regularly. Watts are
    for display; they must never end up in the canonical key or every listing
    would look unique."""
    p = parse_title(
        "Vitron V527 - 2.1 CH Multimedia Speaker, BT/USB/SD/FM - 9000W",
        category="audio",
    )
    assert p.canonical_key is not None
    assert "9000" not in p.canonical_key
    assert "watts" not in p.canonical_key.lower()


def test_generic_no_brand_earbuds_rejected() -> None:
    """Titles like 'TWS BT 5.2 True Wireless In Ear Earbuds' are unbranded
    Chinese imports. Without a brand there's nothing to merge on, so drop them."""
    p = parse_title("TWS BT 5.2 True Wireless In Ear Earbuds Stereo Mini", category="audio")
    assert p.canonical_key is None
