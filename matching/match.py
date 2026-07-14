"""Match a raw listing to an existing Product, or create one.

The category the listing came from is the source of truth — it tells the
matcher which category-specific parser to use and gets denormalized onto the
Product row so category landing pages can filter cheaply.
"""

from __future__ import annotations

from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from db.models import Category, Product
from matching.normalize import parse_title


def _category_id_for(session: Session, slug: str) -> int | None:
    row = session.exec(select(Category).where(Category.slug == slug)).first()
    return row.id if row else None


def _pretty_title_for_phone(brand: str, model: str, specs: dict) -> str:
    storage = specs.get("storage_gb")
    ram = specs.get("ram_gb")
    suffix = f"{ram}/{storage}GB" if storage and ram else (f"{storage}GB" if storage else "")
    return " ".join(x for x in [brand.title(), model.title(), suffix] if x).strip()


def match_or_create_product(
    session: Session,
    *,
    title: str,
    image_url: str | None = None,
    category: str = "phones",
    description: str | None = None,
) -> Product | None:
    parsed = parse_title(title, category=category, description=description)
    if not parsed.canonical_key:
        # v1 hook: drop into LLM disambiguation queue. For v0, just skip.
        return None

    existing = session.exec(
        select(Product).where(Product.canonical_key == parsed.canonical_key)
    ).first()
    if existing:
        return existing

    # Each parser may provide its own display_title (laptops build a rich one
    # with CPU + refurb flag). Phones fall back to the legacy phone builder.
    if parsed.display_title:
        pretty_title = parsed.display_title
    else:
        pretty_title = _pretty_title_for_phone(
            parsed.brand or "unknown",
            parsed.model or "unknown",
            parsed.specs,
        ) or title

    product = Product(
        slug=slugify(parsed.canonical_key.replace("|", "-")),
        canonical_key=parsed.canonical_key,
        brand=parsed.brand or "unknown",
        model=parsed.model or "unknown",
        title=pretty_title,
        image_url=image_url,
        category_slug=category,
        category_id=_category_id_for(session, category),
        specs=parsed.specs or None,
    )
    # Nested transaction (SAVEPOINT) so a UNIQUE-collision only rolls back
    # this insert, not the entire session. This can happen when a merchant
    # lists the same product twice (Gadget World has this) or when two
    # slightly different raw titles collapse to the same canonical key.
    try:
        with session.begin_nested():
            session.add(product)
            session.flush()
    except IntegrityError:
        return session.exec(
            select(Product).where(Product.canonical_key == parsed.canonical_key)
        ).first()
    return product
