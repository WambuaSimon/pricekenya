"""One-shot: re-parse every Listing under the current matcher and move
listings whose canonical_key changed.

Also:
- Deletes listings the matcher now rejects (e.g. suction-cup mounts that
  used to leak into the Cameras category).
- Deletes Product rows left with zero listings.
- Preserves PriceHistory via the listing_id foreign key when a listing
  moves (its id doesn't change).

Runs deterministically off the regex matcher — DOES NOT invoke the LLM
fallback or embedding merge (both would slow the pass and could produce
non-idempotent side effects during batch cleanup). New products created
here have NULL embedding; run `scripts.backfill_embeddings` afterwards.

Usage:
    python -m scripts.normalize_products --dry-run           # report only
    python -m scripts.normalize_products                     # actually write
    python -m scripts.normalize_products --category cameras  # limit scope
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass

from slugify import slugify
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from db.models import Listing, PriceHistory, Product
from db.session import engine
from matching.base import clean_title

# Per-category reject-phrase lists — a listing whose title matches ANY phrase
# here is definite garbage (not the category it landed in). Non-matching
# unparseables are LEFT ALONE because they may have been LLM-parsed originally
# and re-parsing with the regex-only matcher is not authoritative.
#
# Reuses the per-parser NON_XXX_MARKERS tuples so the same rules that reject
# at ingest also drive retroactive cleanup.
from matching.laptop import NON_LAPTOP_MARKERS as _LAPTOP_REJECT
from matching.match import _is_shallow_parse
from matching.normalize import parse_title
from matching.phone import NON_PHONE_MARKERS as _PHONE_REJECT

_REJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "cameras": (
        "camera mount", "camera holder", "camera adapter", "camera bracket",
        "suction cup mount", "action camera holder", "action camera mount",
        "action camera adapter", "helmet mount", "handlebar mount",
        "chest mount", "head mount", "windshield mount", "bike mount",
        "wrist mount", "camera bag", "camera backpack",
    ),
    "phones": _PHONE_REJECT,
    "tablets": _PHONE_REJECT,   # tablet cases/covers/chargers same shape
    "laptops": _LAPTOP_REJECT,
}


def _title_matches_reject(cleaned: str, category: str) -> bool:
    phrases = _REJECT_PHRASES.get(category, ())
    return any(p in cleaned for p in phrases)


@dataclass
class Plan:
    moves: list[tuple[int, int, str, str]]           # (listing_id, target_product_id, old_key, new_key)
    creates: dict[str, tuple[str, str, str]]         # canonical_key → (title, brand, model)
    deletes_listings: list[tuple[int, str]]          # (listing_id, reason_title)
    deletes_products: list[tuple[int, str]]          # (product_id, canonical_key)


def _try_llm_enrich(session: Session, title: str, category: str, regex_key: str):
    """Ask the LLM to try to extract a model_code when regex only produced a
    shallow brand|type key. Returns a ParsedTitle if LLM improves things,
    else None (caller keeps the regex result).
    """
    from matching.llm_extract import extract

    try:
        enriched = extract(session, title=title, category=category)
    except Exception:  # noqa: BLE001
        return None
    if not enriched or not enriched.canonical_key:
        return None
    # Only use LLM key if it's strictly deeper than what regex produced —
    # otherwise we'd churn without gain.
    if enriched.canonical_key.count("|") <= regex_key.count("|"):
        return None
    return enriched


def _plan(session: Session, categories: set[str] | None, use_llm: bool) -> Plan:
    listings = session.exec(select(Listing)).all()
    products = {p.id: p for p in session.exec(select(Product)).all()}

    moves: list[tuple[int, int, str, str]] = []
    # key -> (title, brand, model, category, image_url)
    creates_meta: dict[str, tuple[str, str, str, str, str | None]] = {}
    deletes_listings: list[tuple[int, str]] = []

    # Track resulting product_id per listing for the empty-product sweep.
    target_by_listing: dict[int, int | None] = {}

    for listing in listings:
        product = products.get(listing.product_id)
        if not product:
            continue
        if categories and product.category_slug not in categories:
            # Not in scope — treat as stays.
            target_by_listing[listing.id] = product.id
            continue

        parsed = parse_title(listing.title_on_merchant, category=product.category_slug)
        new_key = parsed.canonical_key

        # If regex gave us a shallow brand|type key AND LLM enrichment is
        # enabled, ask Gemini to try again. Same title-hash cache means
        # 9 JBL listings on the same product cost at most 9 API calls
        # (fewer if the same title repeats across merchants).
        if use_llm and new_key and _is_shallow_parse(new_key, product.category_slug):
            enriched = _try_llm_enrich(
                session, listing.title_on_merchant, product.category_slug, new_key
            )
            if enriched:
                parsed = enriched
                new_key = enriched.canonical_key

        if not new_key:
            # Regex matcher can't parse it. TWO cases:
            #   (a) title explicitly matches a per-category reject phrase
            #       ("camera mount") → definitely garbage, delete.
            #   (b) title just doesn't match the regex parsers — could be a
            #       legit product that was LLM-parsed. Leave in place.
            cleaned = clean_title(listing.title_on_merchant)
            if _title_matches_reject(cleaned, product.category_slug):
                deletes_listings.append((listing.id, listing.title_on_merchant[:80]))
                target_by_listing[listing.id] = None
            else:
                target_by_listing[listing.id] = product.id
            continue

        if new_key == product.canonical_key:
            target_by_listing[listing.id] = product.id
            continue

        # Look for an existing target Product with the new key.
        target = next(
            (p for p in products.values() if p.canonical_key == new_key),
            None,
        )
        if target is None:
            pretty = parsed.display_title or listing.title_on_merchant
            # Inherit image from the source product — the moving listing
            # originally caused (or shared) that product's image.
            creates_meta[new_key] = (
                pretty,
                parsed.brand or "unknown",
                parsed.model or "unknown",
                product.category_slug,
                product.image_url,
            )
            target_by_listing[listing.id] = f"NEW:{new_key}"
        else:
            target_by_listing[listing.id] = target.id
        moves.append((listing.id, target_by_listing[listing.id], product.canonical_key, new_key))

    # Which existing products end up empty?
    surviving: Counter = Counter()
    for _lid, target in target_by_listing.items():
        if isinstance(target, int):
            surviving[target] += 1
    deletes_products = [
        (p.id, p.canonical_key)
        for p in products.values()
        if surviving[p.id] == 0 and (not categories or p.category_slug in categories)
    ]

    creates_out = {k: (v[0], v[1], v[2]) for k, v in creates_meta.items()}
    return Plan(moves=moves, creates=creates_out, deletes_listings=deletes_listings, deletes_products=deletes_products), creates_meta


def _apply(session: Session, plan: Plan, creates_meta: dict) -> None:
    # 1. Create new products (before moves reference them).
    new_ids: dict[str, int] = {}
    for key in plan.creates:
        title, brand, model, category_slug, image_url = creates_meta[key]
        product = Product(
            slug=slugify(key.replace("|", "-")),
            canonical_key=key,
            brand=brand,
            model=model,
            title=title,
            image_url=image_url,
            category_slug=category_slug,
            specs=None,   # scrapers re-populate on next pass
        )
        session.add(product)
        session.flush()
        new_ids[key] = product.id

    # 2. Move listings. Resolve "NEW:<key>" placeholders to real ids.
    for listing_id, target, _old_key, new_key in plan.moves:
        target_id = new_ids[new_key] if isinstance(target, str) else target
        listing = session.get(Listing, listing_id)
        if listing:
            listing.product_id = target_id
            session.add(listing)

    # 3. Delete rejected listings + their referring rows in the RIGHT ORDER.
    # Row-by-row `session.delete(listing)` inside a loop triggers autoflush
    # on the next query, which tries to remove a Listing whose PriceHistory
    # rows are still marked-but-not-yet-committed → FK violation. Bulk
    # DELETE statements per referring table sidesteps the autoflush entirely.
    if plan.deletes_listings:
        listing_ids = [lid for lid, _ in plan.deletes_listings]
        # Any table with FK to listing.id must be cleaned first.
        from db.models import Click
        session.execute(sa_delete(PriceHistory).where(PriceHistory.listing_id.in_(listing_ids)))
        session.execute(sa_delete(Click).where(Click.listing_id.in_(listing_ids)))
        session.execute(sa_delete(Listing).where(Listing.id.in_(listing_ids)))

    session.flush()

    # 4. Delete now-empty products.
    for product_id, _key in plan.deletes_products:
        product = session.get(Product, product_id)
        if not product:
            continue
        # Sanity: recheck listing count now that moves + deletes are flushed.
        remaining = session.exec(
            select(Listing).where(Listing.product_id == product_id).limit(1)
        ).first()
        if remaining is None:
            session.delete(product)

    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report the plan, write nothing")
    parser.add_argument(
        "--category",
        action="append",
        help="Restrict to one or more category slugs (repeatable)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Also call Gemini to enrich shallow brand|type parses "
        "(rate-limited to 15 RPM; cache-deduped by title-hash)",
    )
    args = parser.parse_args()

    categories = set(args.category) if args.category else None

    with Session(engine) as session:
        listings = session.exec(select(Listing)).all()
        plan, creates_meta = _plan(session, categories, use_llm=args.llm)

        print(f"Listings analysed: {len(listings)}")
        print(f"  moves: {len(plan.moves)}")
        print(f"  new products to create: {len(plan.creates)}")
        print(f"  listings to delete (matcher now rejects): {len(plan.deletes_listings)}")
        print(f"  products to delete (empty after moves): {len(plan.deletes_products)}")
        print()

        if plan.deletes_listings:
            print("Listings the matcher now rejects:")
            for lid, title in plan.deletes_listings[:15]:
                print(f"  listing {lid}: {title}")
            if len(plan.deletes_listings) > 15:
                print(f"  ... and {len(plan.deletes_listings) - 15} more")
            print()

        if plan.creates:
            print("New products to create (up to 15):")
            for key, (title, _brand, _model) in list(plan.creates.items())[:15]:
                print(f"  {key}   ({title[:60]})")
            if len(plan.creates) > 15:
                print(f"  ... and {len(plan.creates) - 15} more")
            print()

        if plan.deletes_products:
            print("Products to delete (up to 15):")
            for pid, key in plan.deletes_products[:15]:
                print(f"  {pid}  {key}")
            if len(plan.deletes_products) > 15:
                print(f"  ... and {len(plan.deletes_products) - 15} more")
            print()

        if args.dry_run:
            print("(--dry-run — no writes)")
            return

        _apply(session, plan, creates_meta)
        print("done")


if __name__ == "__main__":
    main()
