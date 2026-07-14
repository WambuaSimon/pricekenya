"""Regression tests for the camera matcher.

The Kenyan camera catalog is heavy on cheap Chinese imports (V380 spy cams,
generic 4K action cams, kids cameras) and very light on real branded DSLRs.
These tests lock in the matcher's tolerance for chunky spec-only titles,
the model-code fallback for un-branded imports, and aggressive accessory
rejection (tripods, mics, bags, memory cards leak into the merchant feeds).
"""

import pytest

from matching.normalize import parse_title


@pytest.mark.parametrize(
    "title,expected_key",
    [
        # Real branded DSLR with model code
        ("Canon EOS 250D DSLR Camera with 18-55mm Lens", "canon|dslr|eos250d"),
        # Action cam brand — Hero version is the model identifier.
        ("GoPro Hero 12 Black 5.3K Action Camera", "gopro|action-cam|hero12"),
        # Chinese security-cam brands recognized by name
        (
            "V380 Mini Wifi Camera 1080p IP Camera Wireless CCTV Night Vision",
            "v380|security-cam|1080p",
        ),
        ("2NLF 4MP 360 View WiFi Security Cameras 5G 2.4G", "2nlf|security-cam|4mp"),
        # Kids camera with a model code
        (
            "LK003 Dual-lens 4K HD Kids Camera - 2.4\" Screen, Yellow",
            "generic|kids-camera|lk003",
        ),
        # Digital-camera with model code
        (
            "6K HD 64MP 18X Zoom Digital Video Camera RX200",
            "generic|digital-camera|rx200",
        ),
        # Generic action cam with only a resolution — still indexable
        (
            "Ultra HD 4K WiFi Action Camera Portable Digital Video Recorder",
            "generic|action-cam|4k",
        ),
        # Generic digital camera with only megapixels — still indexable
        (
            "48 Million Pixel CCD HD Digital Camera Retro Self-Portrait",
            "generic|digital-camera|48mp",
        ),
        # Hikvision security cam with MP as identifier
        ("Hikvision DS-2CD1043G0-I 4MP IP Camera", "hikvision|security-cam|4mp"),
    ],
)
def test_camera_titles(title: str, expected_key: str) -> None:
    parsed = parse_title(title, category="cameras")
    assert parsed.canonical_key == expected_key


@pytest.mark.parametrize(
    "title",
    [
        "Tripod 3120 Adjustable Aluminum Camera & Phone Tripod Stand",
        "Wireless Vlogging Microphone 3-in-1 Dual Mic for DSLR Camera",
        "Big Capacity Photography Camera Waterproof Shoulders Backpack",
        "Camera Stand Heavy Duty Tripod with Phone Holder",
        "Universal Camera Flash Hot Shoe Mount Adapter",
        "32GB SD memory card for cameras Class 10",
        "Camera Bag Waterproof DSLR Case",
        "Lens Cap 58mm Front Cap Cover",
    ],
)
def test_camera_accessories_rejected(title: str) -> None:
    """Merchant camera feeds are polluted with accessories. Matcher must skip them."""
    parsed = parse_title(title, category="cameras")
    assert parsed.canonical_key is None


def test_two_v380_listings_merge_by_brand_and_type() -> None:
    """Same generic security cam from two merchants must merge on brand + type
    even when spec text differs slightly."""
    a = parse_title(
        "V380 Mini Wifi Camera 1080p IP Camera CCTV Night Vision",
        category="cameras",
    ).canonical_key
    b = parse_title(
        "V380 Pro 1080P HD Wireless Wifi IP Security Camera Full HD",
        category="cameras",
    ).canonical_key
    assert a == b == "v380|security-cam|1080p"


def test_generic_with_no_signal_dropped() -> None:
    """A title with no brand, no model code, no resolution, and no MP claim
    has nothing to key on — better to drop than false-merge everything to
    'generic|digital-camera'."""
    p = parse_title("HD Digital Camera Portable Video Recorder", category="cameras")
    assert p.canonical_key is None
