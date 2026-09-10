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

#: Distinct live merchants a product needs before a shopper can genuinely
#: cross-shop it. Powers both the "Only comparable products" facet and the
#: category page's "Comparable" stat.
#:
#: This was the same number as app/indexing.py's MIN_DISTINCT_MERCHANTS until
#: 2026-09-09, and several comments described them as one rule. They are not,
#: and conflating them again would break something: indexing asks "is this
#: page worth serving to Google", which a single-offer page can be, while
#: this asks "can you compare prices here", which by definition needs two.
#: Lowering indexing to 1 while leaving this at 2 is the whole point of the
#: split — do not re-link them.
MIN_MERCHANTS_TO_COMPARE = 2


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
    # "Comparable" = listed by MIN_MERCHANTS_TO_COMPARE+ distinct merchants,
    # the same rule as the category page's `compared_count` stat. NOT the
    # same as the indexing threshold any more — see that constant above. Unlike the "In stock only" facet this replaced,
    # it genuinely narrows the grid: single-merchant products are the
    # majority of the catalog and there is nothing to compare on them.
    Facet("comparable", "Only comparable products", "bool", "comparable"),
    # "In stock only" removed 2026-08-25. Category pages now restrict to
    # in-stock listings unconditionally (see the base query in
    # app/routes/categories.py for why), which left this facet unable to
    # change anything. A checkbox that does nothing when ticked is worse
    # than an absent one.
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
