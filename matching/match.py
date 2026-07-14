"""Match a raw listing to an existing Product, or create one.

The category the listing came from is the source of truth — it tells the
matcher which category-specific parser to use and gets denormalized onto the
Product row so category landing pages can filter cheaply.

Behavior gated by settings:
- LLM_FALLBACK_ENABLED: on regex-parser failure, call Gemini via
  `matching.llm_extract.extract`. Off by default.
- EMBEDDING_ENABLED: before creating a new Product, compute a MiniLM
  embedding and near-neighbour search inside the same category. Auto-merge
  at cosine ≥0.95; log 0.90–0.95 candidates for admin review. Only fires
  when the encoder has been explicitly allowed (scraper/CLI paths call
  `matching.embeddings.allow_encode()` at boot).
"""

from __future__ import annotations

import logging

from slugify import slugify
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import settings
from db.models import Category, Product, ProductMergeCandidate
from matching.normalize import parse_title

logger = logging.getLogger(__name__)


def _category_id_for(session: Session, slug: str) -> int | None:
    row = session.exec(select(Category).where(Category.slug == slug)).first()
    return row.id if row else None


def _pretty_title_for_phone(brand: str, model: str, specs: dict) -> str:
    storage = specs.get("storage_gb")
    ram = specs.get("ram_gb")
    suffix = f"{ram}/{storage}GB" if storage and ram else (f"{storage}GB" if storage else "")
    return " ".join(x for x in [brand.title(), model.title(), suffix] if x).strip()


# Categories where a 2-segment canonical_key (brand|type) is a red flag —
# the parser bailed on model-code extraction and the bucket is at risk of
# collapsing unrelated SKUs. LLM enrichment fires for these.
_SHALLOW_KEY_CATEGORIES = frozenset(
    {"audio", "cameras", "cooking", "kettles", "blenders", "toasters", "ironing-laundry"}
)


def _is_shallow_parse(canonical_key: str, category: str) -> bool:
    """A brand|type-only key in a category where richer keys are expected."""
    if category not in _SHALLOW_KEY_CATEGORIES:
        return False
    return canonical_key.count("|") <= 1


def _try_llm_fallback(session: Session, *, title: str, category: str):
    """Return a ParsedTitle from Gemini, or None. Never raises."""
    if not (settings.llm_fallback_enabled and settings.gemini_api_key):
        return None
    try:
        from matching.llm_extract import extract  # lazy: web app never triggers
    except Exception:  # noqa: BLE001
        return None
    try:
        return extract(session, title=title, category=category)
    except Exception as exc:  # noqa: BLE001 — silent-drop is the safety net
        logger.debug("llm extract failed for %r: %s", title[:80], exc)
        return None


def _embedding_ready() -> bool:
    """Only fire the embedding branch when scraper/CLI code has opted in."""
    if not settings.embedding_enabled:
        return False
    try:
        from matching import embeddings
    except Exception:  # noqa: BLE001
        return False
    return embeddings.ALLOW_ENCODE


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
        parsed = _try_llm_fallback(session, title=title, category=category)
        if not parsed or not parsed.canonical_key:
            return None
    elif _is_shallow_parse(parsed.canonical_key, category):
        # Regex gave us a brand+type key with no model identifier — this
        # is what collapses "JBL Charge 5", "JBL Xtreme 4", "JBL Clip5",
        # "JBL PartyBox 300" all into a single `jbl|speaker` bucket. Ask
        # the LLM to try model_code extraction; if it succeeds AND its
        # composed key is deeper than the regex one, prefer it. Otherwise
        # fall back to the regex result — never worse than today.
        enriched = _try_llm_fallback(session, title=title, category=category)
        if (
            enriched
            and enriched.canonical_key
            and enriched.canonical_key.count("|") > parsed.canonical_key.count("|")
        ):
            parsed = enriched

    existing = session.exec(
        select(Product).where(Product.canonical_key == parsed.canonical_key)
    ).first()
    if existing:
        _maybe_backfill_embedding(session, existing, parsed=parsed, fallback_title=title)
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

    # Phase 1: before creating a new Product, look for a near-duplicate by
    # embedding. Auto-merge if strong signal AND loose key match, log a
    # candidate if borderline.
    embed_bytes: bytes | None = None
    if _embedding_ready():
        embed_bytes, existing_from_similarity = _embedding_merge_check(
            session,
            category_slug=category,
            title_for_embed=pretty_title,
            _candidate_key=parsed.canonical_key,
            _candidate_specs=parsed.specs,
        )
        if existing_from_similarity is not None:
            return existing_from_similarity

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
        embedding=embed_bytes,
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

    # After the insert commits (via caller), we may want to log a review
    # candidate. Do it now while we hold the new product id.
    if embed_bytes is not None and _embedding_ready():
        _maybe_log_merge_candidate(
            session,
            source_product=product,
            category_slug=category,
            source_title=title,
            source_specs=parsed.specs or None,
        )
    return product


# ---------------------------------------------------------------------------
# Phase 1 helpers
# ---------------------------------------------------------------------------

AUTO_MERGE_THRESHOLD = 0.95
REVIEW_MERGE_THRESHOLD = 0.90

# Structured spec fields that MUST match between two products for them to be
# a plausible merge candidate. If either product has a value for one of these
# and the values differ, the pair is not the same SKU regardless of what
# MiniLM cosine says (LG 75" ≠ LG 65", 128GB ≠ 256GB, 2/32 ≠ 4/64).
_LOAD_BEARING_NUMERIC_SPECS = frozenset(
    {
        "screen_inches",
        "size_inches",
        "storage_gb",
        "ram_gb",
        "capacity_liters",
        "capacity_kg",
        "capacity_ah",
        "capacity_mah",
        "watts",
        "voltage_v",
        "burners",
        "slots",
        "megapixels",
    }
)


def _numeric_specs_conflict(a_specs: dict | None, b_specs: dict | None) -> bool:
    """True when the two spec dicts share a load-bearing numeric key and
    disagree on it. Silent on missing keys — one-sided nulls don't conflict.
    """
    if not a_specs or not b_specs:
        return False
    for key in _LOAD_BEARING_NUMERIC_SPECS:
        va = a_specs.get(key)
        vb = b_specs.get(key)
        if va is None or vb is None:
            continue
        # Cast both to float so 55 == 55.0.
        try:
            if float(va) != float(vb):
                return True
        except (TypeError, ValueError):
            if va != vb:
                return True
    return False


def _canonical_key_model_conflict(a: str, b: str) -> bool:
    """True when two canonical_keys clearly encode different model codes
    or numeric specs at the same structural position.

    Catches: LG 75 vs 65, MK220 vs MK270, Realme C11 vs C100I. These are
    high-cosine false positives MiniLM can't distinguish.
    Ignores: pure formatting differences (flip-7 vs flip7) and length
    differences (macbook-air|m4|16|512 vs macbook-air|16|512, where the
    reviewer should decide).
    """
    parts_a = a.split("|")
    parts_b = b.split("|")
    common = min(len(parts_a), len(parts_b))
    for i in range(common):
        pa = parts_a[i].replace("-", "").replace(" ", "")
        pb = parts_b[i].replace("-", "").replace(" ", "")
        if pa == pb:
            continue
        # Both pure-digit and differ → hard conflict (55 vs 65).
        if pa.isdigit() and pb.isdigit():
            return True
        # Both alpha+digit (model-code shape) and digit runs differ →
        # different model codes (mk220 vs mk270, c11 vs c100i).
        digits_a = "".join(c for c in pa if c.isdigit())
        digits_b = "".join(c for c in pb if c.isdigit())
        alpha_a = "".join(c for c in pa if c.isalpha())
        alpha_b = "".join(c for c in pb if c.isalpha())
        if alpha_a and digits_a and alpha_b and digits_b and digits_a != digits_b:
            return True
    return False


def _obviously_different_products(
    a_specs: dict | None, a_key: str, b_specs: dict | None, b_key: str
) -> bool:
    """Guardrail against MiniLM's blind spot: cosine can't tell 55" from 65".
    Returns True when structured signals prove the two are different SKUs."""
    if _numeric_specs_conflict(a_specs, b_specs):
        return True
    if _canonical_key_model_conflict(a_key, b_key):
        return True
    return False


def _canonical_key_matches_loosely(a: str, b: str) -> bool:
    """True when two canonical_keys are equivalent modulo hyphens and spaces.

    Guards against MiniLM's blind spot on short titles — it happily gives
    0.98+ cosine to genuine model-variant pairs like `oppo|a5|64|4` vs
    `oppo|a5s|64|4`, or `spark-40|128` vs `spark-40|256`. Auto-merge only
    when the two keys really do encode the same product (differing by
    formatting artifacts like `flip-7` vs `flip7`), otherwise fall through
    to the review band even at high cosine.
    """
    def _normalize(k: str) -> str:
        # Preserve pipe separators (they carry structural meaning) but
        # collapse hyphens/spaces WITHIN each field.
        return "|".join(part.replace("-", "").replace(" ", "") for part in k.split("|"))

    return _normalize(a) == _normalize(b)


def _embedding_merge_check(
    session: Session,
    *,
    category_slug: str,
    title_for_embed: str,
    _candidate_key: str | None = None,
    _candidate_specs: dict | None = None,
) -> tuple[bytes | None, Product | None]:
    """Compute the embedding for the would-be-new product and check neighbours.

    Returns `(embedding_bytes, auto_merge_target_or_None)`.
    - If a neighbour has cosine ≥ AUTO_MERGE_THRESHOLD, return
      `(embedding_bytes, that_product)` so the caller can early-return.
    - Otherwise return `(embedding_bytes, None)` — the caller creates the new
      Product and stores the embedding; the review-band candidate is written
      separately once the new product id is known.
    """
    from matching import embeddings

    try:
        vec = embeddings.encode(title_for_embed)
    except Exception as exc:  # noqa: BLE001
        logger.debug("embedding encode failed: %s", exc)
        return None, None

    try:
        neighbours = embeddings.find_nearest(
            session, category_slug=category_slug, vec=vec, top_k=8
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("embedding find_nearest failed: %s", exc)
        return vec, None

    if neighbours:
        best_product, best_sim = neighbours[0]
        # Structural guardrail: reject before either auto-merge or review
        # if specs / canonical_key positions clearly disagree. This is what
        # keeps LG 75" from proposing to merge with LG 65".
        if _obviously_different_products(
            best_product.specs,
            best_product.canonical_key,
            _candidate_specs,
            _candidate_key or "",
        ):
            return vec, None

        # Auto-merge requires BOTH high cosine AND loose canonical_key
        # equivalence — MiniLM can't tell a5 from a5s on 5-word titles,
        # so cosine alone is not enough to be destructive.
        if best_sim >= AUTO_MERGE_THRESHOLD and _canonical_key_matches_loosely(
            best_product.canonical_key, _candidate_key or ""
        ):
            return vec, best_product
        # Everything else in the review band (including 0.95+ pairs that
        # failed the key guardrail) goes to the manual queue.
        if best_sim >= REVIEW_MERGE_THRESHOLD:
            session.info["_pending_merge_candidate"] = (best_product.id, float(best_sim))
    return vec, None


def _maybe_log_merge_candidate(
    session: Session,
    *,
    source_product: Product,
    category_slug: str,
    source_title: str,
    source_specs: dict | None,
) -> None:
    pending = session.info.pop("_pending_merge_candidate", None)
    if not pending:
        return
    target_id, sim = pending
    if source_product.id is None or target_id == source_product.id:
        return
    row = ProductMergeCandidate(
        source_product_id=source_product.id,
        target_product_id=target_id,
        similarity=sim,
        source_title=source_title[:1024],
        source_specs=source_specs,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        # Duplicate pair — noop, the earlier candidate stands.
        pass


def _maybe_backfill_embedding(
    session: Session,
    product: Product,
    *,
    parsed,
    fallback_title: str,
) -> None:
    """Opportunistically populate embedding on an existing product that lacks one.

    Keeps the neighbour set dense so the next merge check has better recall.
    Safe to skip on error — merge behaviour degrades gracefully.
    """
    if not _embedding_ready():
        return
    if getattr(product, "embedding", None) is not None:
        return
    from matching import embeddings

    text = parsed.display_title or product.title or fallback_title
    try:
        product.embedding = embeddings.encode(text)
        session.add(product)
    except Exception as exc:  # noqa: BLE001
        logger.debug("opportunistic embedding backfill failed: %s", exc)
