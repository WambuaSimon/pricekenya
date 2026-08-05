"""Fill Product.description via Gemini for products the scraper couldn't get one from.

Why this exists:
- Google Search Console (2026-08-04) reports 4,317 URLs in "Discovered –
  currently not indexed". Most are product pages Google judges thin
  because they're basically just an offer table with no descriptive copy.
- Product.description already renders on /p/* as "About this product" and
  is included in the Product JSON-LD (see CONTEXT.md §8d). Scrapers were
  supposed to fill it per-merchant but coverage is patchy.
- Generating 80-120 words per product with real spec context from the
  title unblocks Google's indexing bar without waiting on scraper work.

Design:
- Selects products whose description is NULL or empty AND (optionally)
  match a --category filter.
- For each, calls Gemini 2.0 Flash with a category-aware prompt asking
  for a plain-text description, then writes it back.
- Client-side sleep between calls stays well under the free-tier 15 RPM.
- Deliberately idempotent — a re-run on the same DB skips already-filled
  products.
- --dry-run prints the generated description to stdout without touching
  the DB, so the prompt can be tuned before committing 7K DB writes.

Run:
    python -m scripts.enrich_descriptions --limit 20 --dry-run
    python -m scripts.enrich_descriptions --limit 100 --category phones
    python -m scripts.enrich_descriptions --limit 100
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

from sqlmodel import Session, or_, select

from app.config import settings
from db.models import Product
from db.session import engine

logger = logging.getLogger(__name__)

# Free-tier Gemini 2.0 Flash is 15 requests/minute. 5 seconds between calls
# keeps us at 12 RPM with headroom for the matching pipeline running
# alongside on the same key. Tune down to 3s if the matching pipeline
# isn't active during a batch run.
_SECONDS_BETWEEN_CALLS = 5.0

# Cap tokens hard so a runaway prompt (bad model output) can't blow $$.
# 120 words * ~1.5 tokens/word = ~180. 300 is generous headroom.
_MAX_OUTPUT_TOKENS = 300


_PROMPT_TEMPLATE = """You write concise product descriptions for a Kenyan e-commerce price-comparison site.

Product: {title}
Brand: {brand}
Model: {model}
Category: {category}

Write 80-120 words describing this product for someone comparing prices across Kenyan merchants. Cover, in order:
- What the product is (1 sentence).
- Key specs and features implied by the title and model (2-3 sentences).
- Who it's for or the typical use case (1 sentence).

Hard constraints:
- Do NOT mention any specific price or KSh amount. Prices come from live merchant listings and would conflict.
- Do NOT include marketing hype: no "amazing", "revolutionary", "must-have", "state-of-the-art".
- No headings, no bullets, no markdown. Plain paragraph(s) only.
- If a spec isn't clearly implied by the title/model, do NOT invent it.
- Kenya-relevant context is fine where genuinely applicable (M-Pesa compatibility for phones, off-grid capability for solar, dust/heat tolerance for outdoor products). Skip if forced.

Output the description text only. No preamble."""


def _get_client() -> Any:
    """Lazy import + construct the Gemini client. Returns None if the
    google-genai extra isn't installed or GEMINI_API_KEY isn't set."""
    if not settings.gemini_api_key:
        logger.error(
            "GEMINI_API_KEY is unset. Set it in the environment or app.config.settings."
        )
        return None
    try:
        from google import genai  # type: ignore[import-not-found]
    except ImportError:
        logger.error(
            "google-genai not installed. Install with: pip install -e '.[embeddings]' "
            "or add the package directly."
        )
        return None
    return genai.Client(api_key=settings.gemini_api_key)


def _generate_description(client: Any, product: Product) -> str | None:
    """One Gemini call → plain-text description, or None on error."""
    try:
        from google.genai import types  # type: ignore[import-not-found]
    except ImportError:
        return None

    prompt = _PROMPT_TEMPLATE.format(
        title=product.title or "",
        brand=(product.brand or "").title() or "unknown",
        model=product.model or "unknown",
        category=product.category_slug or "unknown",
    )

    config = types.GenerateContentConfig(
        response_mime_type="text/plain",
        temperature=0.2,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )

    try:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 — surface everything to the log
        logger.warning("gemini call failed for product %s: %s", product.slug, exc)
        return None

    text = getattr(resp, "text", None)
    if not text:
        return None
    return text.strip()


def _select_products(
    session: Session, *, category: str | None, limit: int
) -> list[Product]:
    stmt = select(Product).where(
        or_(Product.description.is_(None), Product.description == "")
    )
    if category:
        stmt = stmt.where(Product.category_slug == category)
    # Deterministic order so incremental runs cover the catalog uniformly.
    stmt = stmt.order_by(Product.id.asc()).limit(limit)
    return list(session.exec(stmt).all())


def run(*, category: str | None, limit: int, dry_run: bool) -> int:
    client = _get_client()
    if client is None:
        return 1

    with Session(engine) as session:
        products = _select_products(session, category=category, limit=limit)
        if not products:
            print("no products need enrichment (matching the filter)")
            return 0

        print(
            f"enriching {len(products)} product(s)"
            f"{f' in category {category!r}' if category else ''}"
            f"{' (dry run)' if dry_run else ''}"
        )

        written = 0
        for i, product in enumerate(products, start=1):
            desc = _generate_description(client, product)
            if not desc:
                print(f"  [{i}/{len(products)}] {product.slug}: SKIPPED (no output)")
            elif dry_run:
                print(f"  [{i}/{len(products)}] {product.slug}:\n{desc}\n")
            else:
                product.description = desc
                session.add(product)
                session.commit()
                written += 1
                print(f"  [{i}/{len(products)}] {product.slug}: wrote {len(desc)} chars")

            # Skip the sleep after the final iteration.
            if i < len(products):
                time.sleep(_SECONDS_BETWEEN_CALLS)

    if not dry_run:
        print(f"done — wrote {written} description(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Max products to enrich in this run (default: 50)",
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Only enrich products in this category_slug (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print generated descriptions to stdout without touching the DB",
    )
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 5000:
        parser.error("--limit must be between 1 and 5000")
    return run(category=args.category, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
