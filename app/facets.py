"""Per-category filter facets for /c/<slug> pages.

Facets are declarative: each one names a query-param key, a display label,
the kind of filter (enum/range/bool), and where to read the values from
(a Product column, or a nested key inside Product.specs). The category
route consumes this list to (a) know which query params to parse, (b)
build the SQL filter clauses, and (c) render the sidebar UI.

Adding a new facet is a one-line change here; no route/template edits
needed unless the facet kind is new.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Facet:
    """One filter axis on a category page.

    key    — query-param name (repeatable for enum: ?brand=samsung&brand=xiaomi)
    label  — display name in the sidebar
    kind   — 'enum'  → multi-select checkbox list
             'range' → single "max value" input (min is always 0)
             'bool'  → single toggle
    source — 'brand', 'category_slug', 'in_stock', 'min_price', or
             'specs.<key>' for JSON-nested spec values
    """

    key: str
    label: str
    kind: str
    source: str


# Facets that apply to every category page.
UNIVERSAL: tuple[Facet, ...] = (
    Facet("brand", "Brand", "enum", "brand"),
    Facet("price_max", "Max price (KSh)", "range", "min_price"),
    Facet("in_stock", "In stock only", "bool", "in_stock"),
)


# Category-specific facets. Only fires on leaf pages whose slug matches —
# parent categories (e.g. `electronics`) aggregate over unlike specs and
# would show mostly-empty facet lists.
PER_CATEGORY: dict[str, tuple[Facet, ...]] = {
    "phones": (
        Facet("storage", "Storage (GB)", "enum", "specs.storage_gb"),
        Facet("ram", "RAM (GB)", "enum", "specs.ram_gb"),
    ),
    "tablets": (
        Facet("storage", "Storage (GB)", "enum", "specs.storage_gb"),
        Facet("ram", "RAM (GB)", "enum", "specs.ram_gb"),
    ),
    "laptops": (
        Facet("storage", "Storage (GB)", "enum", "specs.storage_gb"),
        Facet("ram", "RAM (GB)", "enum", "specs.ram_gb"),
    ),
    "tvs": (
        Facet("screen_inches", "Screen size (inches)", "enum", "specs.screen_inches"),
    ),
    "refrigerators": (
        Facet("capacity_liters", "Capacity (L)", "enum", "specs.capacity_liters"),
    ),
    "washers-dryers": (
        Facet("capacity_kg", "Capacity (kg)", "enum", "specs.capacity_kg"),
    ),
    "inverters": (
        Facet("watts", "Rated power (W)", "enum", "specs.watts"),
    ),
    "solar-panels": (
        Facet("watts", "Panel wattage (W)", "enum", "specs.watts"),
    ),
    "solar-batteries": (
        Facet("capacity_ah", "Capacity (Ah)", "enum", "specs.capacity_ah"),
    ),
}


def facets_for(category_slug: str) -> list[Facet]:
    """Return the ordered list of facets to render for `category_slug`.

    Universal facets always appear first (brand, price, stock) so the
    sidebar's top section is stable across every category page. Per-
    category facets come after, and only for leaves we've configured.
    """
    return list(UNIVERSAL) + list(PER_CATEGORY.get(category_slug, ()))
