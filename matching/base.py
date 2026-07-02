"""Shared matcher primitives used by every category-specific parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from slugify import slugify

__all__ = ["ParsedTitle", "clean_title", "slugify"]


@dataclass
class ParsedTitle:
    """Result of parsing a merchant listing title.

    Any category parser produces one of these. `specs` is category-specific
    (e.g. {"storage_gb": 256, "ram_gb": 8} for phones; {"screen_inches": 55}
    for TVs). `canonical_key` is what merges listings across merchants — if
    None, the title couldn't be parsed and the ingest pipeline drops the row.
    `display_title` is the pretty name shown on cards / product pages; if not
    provided, the caller synthesises one from brand + model.
    """

    brand: str | None = None
    model: str | None = None
    canonical_key: str | None = None
    specs: dict[str, Any] = field(default_factory=dict)
    display_title: str | None = None


def clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.lower()).strip()
