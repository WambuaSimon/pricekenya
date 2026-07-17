"""Seed the category tree.

The tree is defined as nested tuples (slug, name, [children]). This is the
canonical source of truth for category structure — CONTEXT.md describes what's
here, DB rows follow it. Re-running this is idempotent: it upserts by slug.
"""

from __future__ import annotations

from sqlmodel import Session, select

from db.models import Category
from db.session import engine, init_db

# (slug, display_name, [children])
CATEGORY_TREE: list[tuple[str, str, list]] = [
    ("electronics", "Electronics", [
        ("phones-tablets-accessories", "Phones, Tablets & Accessories", [
            ("phones", "Phones", []),
            ("tablets", "Tablets", []),
            ("phone-tablet-accessories", "Phone & Tablet Accessories", []),
        ]),
        ("computing", "Computing", [
            ("laptops", "Laptops", []),
            ("storage", "Storage", []),
            ("peripherals-accessories", "Peripherals & Accessories", []),
            ("printers-scanners", "Printers & Scanners", []),
        ]),
        ("tvs", "TVs", []),
        ("audio", "Audio", []),
        ("cameras", "Cameras", []),
        ("appliances", "Appliances", [
            ("cooking", "Cooking", []),
            ("large-appliances", "Large Appliances", [
                ("refrigerators", "Refrigerators", []),
                ("freezers", "Freezers", []),
                ("water-dispensers-coolers", "Water Dispensers & Coolers", []),
                ("washers-dryers", "Washers & Dryers", []),
                # Split out of washers-dryers on 2026-07-17. A KSh 80k
                # built-in dishwasher shares no buyer intent with washing
                # machines; browsing them together was a bad UX.
                ("dishwashers", "Dishwashers", []),
            ]),
            ("small-appliances", "Small Appliances", [
                ("blenders", "Blenders", []),
                ("toasters", "Toasters", []),
                ("kettles", "Kettles", []),
                ("ironing-laundry", "Ironing & Laundry", []),
                # Newmatic + Hotpoint + Jumia all stock built-in and
                # counter-top coffee machines at KSh 70k–200k+.
                ("coffee-machines", "Coffee Machines", []),
            ]),
        ]),
        ("gaming", "Gaming", [
            ("playstation-5", "PlayStation 5", []),
            ("xbox-series", "Xbox Series X / S", []),
            ("nintendo-switch", "Nintendo Switch", []),
            ("console-accessories", "Console Accessories", []),
            ("games-digital-cards", "Games & Digital Cards", []),
        ]),
        # Solar & backup power — Kenya-specific opportunity; grid reliability
        # + off-grid rural market make this the highest-intent new vertical.
        ("power-energy", "Solar & Power", [
            ("inverters", "Inverters", []),
            ("solar-panels", "Solar Panels", []),
            ("solar-batteries", "Solar Batteries", []),
        ]),
    ]),
    # Home & Kitchen fixtures — hardware/plumbing/decor that sits outside the
    # "Electronics" umbrella. Introduced 2026-07-17 driven by Newmatic's
    # built-in-kitchen catalog which sells substantial SKU volume across
    # sinks, countertops, and kitchen hardware that had no home before.
    ("home-kitchen", "Home & Kitchen", [
        ("kitchen-fixtures", "Kitchen Fixtures", [
            ("kitchen-sinks-taps", "Sinks & Taps", []),
            ("countertops", "Countertops", []),
            ("splashbacks", "Splashbacks", []),
            ("kitchen-hardware", "Kitchen Hardware", []),
            ("utensils", "Utensils & Kitchenware", []),
        ]),
        ("bathroom-fixtures", "Bathroom Fixtures", [
            ("toilets", "Toilets", []),
        ]),
    ]),
]


def _upsert(session: Session, slug: str, name: str, parent_id: int | None, order: int) -> Category:
    existing = session.exec(select(Category).where(Category.slug == slug)).first()
    if existing:
        existing.name = name
        existing.parent_id = parent_id
        existing.sort_order = order
        session.add(existing)
        return existing
    cat = Category(slug=slug, name=name, parent_id=parent_id, sort_order=order)
    session.add(cat)
    session.flush()
    return cat


def _walk(session: Session, nodes: list, parent_id: int | None) -> None:
    for order, (slug, name, children) in enumerate(nodes):
        cat = _upsert(session, slug, name, parent_id, order)
        if children:
            _walk(session, children, cat.id)


def run() -> None:
    init_db()
    with Session(engine) as session:
        _walk(session, CATEGORY_TREE, None)
        session.commit()
        print(f"Category tree seeded: {session.exec(select(Category)).all().__len__()} nodes.")


if __name__ == "__main__":
    run()
