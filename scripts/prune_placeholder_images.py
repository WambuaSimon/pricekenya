"""One-shot: null out Product.image_url values that point at merchant
lazy-load placeholders instead of real product photos.

Fixes the "infinite spinner" case where the product card renders an
`<img>` for e.g. Avechi's `prod_loading.gif` — a real GIF file that
animates a spinner and never resolves to a photo.

After running against prod, the next scrape pass will populate real
`image_url` values via the (now-fixed) WooCommerce extractor.

Idempotent. Prints one line per pruned product and a summary at the end.

Usage:
    python -m scripts.prune_placeholder_images                # apply
    python -m scripts.prune_placeholder_images --dry-run      # preview
"""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from db.models import Product
from db.session import engine
from scrapers.common.woocommerce import is_placeholder_image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write")
    args = parser.parse_args()

    with Session(engine) as session:
        products = session.exec(select(Product).where(Product.image_url.is_not(None))).all()
        pruned = 0
        for p in products:
            if not is_placeholder_image(p.image_url):
                continue
            pruned += 1
            print(f"  prune  id={p.id}  slug={p.slug}  was={p.image_url}")
            if not args.dry_run:
                p.image_url = None
                session.add(p)

        if not args.dry_run:
            session.commit()

        print()
        print(f"scanned:  {len(products)}")
        print(f"pruned:   {pruned}  (image_url reset to NULL)")
        if args.dry_run:
            print("(--dry-run — no writes)")


if __name__ == "__main__":
    main()
