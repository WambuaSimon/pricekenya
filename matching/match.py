"""Match a raw listing to an existing Product, or create one."""

from __future__ import annotations

from sqlmodel import Session, select

from db.models import Product
from matching.normalize import parse_title
from slugify import slugify


def match_or_create_product(
    session: Session,
    *,
    title: str,
    image_url: str | None = None,
    category: str = "phone",
) -> Product | None:
    parsed = parse_title(title)
    if not parsed.canonical_key:
        # v1 hook: drop into LLM disambiguation queue. For v0, just skip.
        return None

    existing = session.exec(
        select(Product).where(Product.canonical_key == parsed.canonical_key)
    ).first()
    if existing:
        return existing

    pretty_title = " ".join(
        x for x in [
            (parsed.brand or "").title(),
            (parsed.model or "").title(),
            f"{parsed.ram_gb}/{parsed.storage_gb}GB" if parsed.storage_gb and parsed.ram_gb
            else (f"{parsed.storage_gb}GB" if parsed.storage_gb else ""),
        ] if x
    ).strip()

    product = Product(
        slug=slugify(parsed.canonical_key.replace("|", "-")),
        canonical_key=parsed.canonical_key,
        brand=parsed.brand or "unknown",
        model=parsed.model or "unknown",
        title=pretty_title or title,
        storage_gb=parsed.storage_gb,
        ram_gb=parsed.ram_gb,
        image_url=image_url,
        category=category,
    )
    session.add(product)
    session.flush()
    return product
