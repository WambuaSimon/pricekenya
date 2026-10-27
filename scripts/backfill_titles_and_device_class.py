"""One-shot: apply the two display fixes from matching/match.py to rows that
were written before it shipped.

Both defects are display-only and so is this backfill:

  1. Doubled brand in `title` ("Nokia Nokia 105"), from a parser that left the
     brand on the front of `model`. 209 products on prod 2026-10-27.
  2. Tablets and smartwatches sitting in `category_slug='phones'`, because a
     merchant's phones page carries them. 32 products.

`canonical_key`, `slug`, `model` and `specs` are NOT touched. The key carries
the same doubling and is deliberately left alone: it is the matching identity,
so rewriting it would re-bucket live products and split them from their own
listings. `slug` is left for the same reason plus a second one — it is the
public URL, and changing it would 404 every indexed link.

Idempotent: a row stops matching once fixed. Safe to re-run.

Usage:
    python -m scripts.backfill_titles_and_device_class --dry-run
    python -m scripts.backfill_titles_and_device_class
    python -m scripts.backfill_titles_and_device_class --category phones
"""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from db.models import Category, Product
from db.session import engine
from matching.match import _pretty_title_for_phone, _refine_category, _strip_leading_brand


def _fixed_title(product: Product) -> str | None:
    """The de-duplicated title, or None when nothing changes.

    Rebuilt from brand/model/specs rather than regex-replacing the stored
    string, so the result matches exactly what the matcher would write for
    this row today -- including the storage suffix.
    """
    brand, model = (product.brand or ""), (product.model or "")
    if not brand or not model:
        return None
    if _strip_leading_brand(brand, model) == model:
        return None  # no doubling
    rebuilt = _pretty_title_for_phone(brand, model, product.specs or {})
    return rebuilt if rebuilt and rebuilt != product.title else None


def _run(session: Session, categories: set[str] | None, dry: bool) -> None:
    q = select(Product)
    if categories:
        q = q.where(Product.category_slug.in_(list(categories)))
    products = session.exec(q.order_by(Product.id)).all()
    print(f"scanning {len(products)} products")

    cat_ids = {c.slug: c.id for c in session.exec(select(Category)).all()}
    retitled = moved = 0

    for product in products:
        new_title = _fixed_title(product)
        if new_title:
            print(f"  title  {product.slug}\n    - {product.title}\n    + {new_title}")
            retitled += 1
            if not dry:
                product.title = new_title
                session.add(product)

        # Refine against the title the shopper will actually see.
        target = _refine_category(product.category_slug, new_title or product.title)
        if target != product.category_slug:
            print(f"  move   {product.slug}: {product.category_slug} -> {target}")
            moved += 1
            if not dry:
                product.category_slug = target
                product.category_id = cat_ids.get(target)
                session.add(product)

    if not dry:
        session.commit()
    print(f"\ndone — {retitled} retitled, {moved} recategorised")
    if dry:
        print("(--dry-run — no writes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--category", action="append", help="Limit to category slug(s)")
    args = parser.parse_args()
    with Session(engine) as session:
        _run(session, set(args.category) if args.category else None, args.dry_run)


if __name__ == "__main__":
    main()
