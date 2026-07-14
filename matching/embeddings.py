"""MiniLM-based product embeddings for near-duplicate reconciliation.

Only imported from scraper/CLI paths. The FastAPI web app must never touch
this module — its heavy dependency (sentence-transformers pulls PyTorch,
~500MB installed, ~90MB model download on first use) would blow Render's
web-tier boot budget.

To keep the web app safe:
- `sentence_transformers` and `numpy` are imported lazily inside `_load()`
  and `_vec()`.
- `encode()` refuses to run unless a scraper/CLI entrypoint has flipped
  `ALLOW_ENCODE` on via `allow_encode()`. A stray `encode(...)` call from
  request-handler code raises RuntimeError.

Storage: MiniLM produces 384-dim float32 → 1536 bytes per product, written
straight into `Product.embedding` (LargeBinary).

Nearest-neighbour search is a naive O(N) scan over same-category products.
Migrate to pgvector when a category exceeds ~50k products or `find_nearest`
p95 breaks 100ms.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from db.models import Product

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


# Entrypoints (scrapers, scripts) call `allow_encode()` at startup. The web
# app never does, so an accidental import from an HTTP handler still raises
# rather than silently loading PyTorch.
ALLOW_ENCODE: bool = False


def allow_encode() -> None:
    global ALLOW_ENCODE
    ALLOW_ENCODE = True


_MODEL: SentenceTransformer | None = None
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384
EMBED_BYTES = EMBED_DIM * 4  # float32


def _load():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        _MODEL = SentenceTransformer(_MODEL_NAME)
    return _MODEL


def _np():
    import numpy as np  # noqa: PLC0415

    return np


def encode(text: str) -> bytes:
    if not ALLOW_ENCODE:
        raise RuntimeError(
            "embeddings.encode called without allow_encode() — the web app "
            "must never load sentence-transformers. Flip the flag in your "
            "scraper/CLI entrypoint."
        )
    if not text:
        text = " "
    np = _np()
    v = _load().encode(text, normalize_embeddings=True).astype(np.float32)
    return v.tobytes()


def encode_batch(texts: list[str]) -> list[bytes]:
    if not ALLOW_ENCODE:
        raise RuntimeError("embeddings.encode_batch called without allow_encode()")
    if not texts:
        return []
    np = _np()
    matrix = _load().encode(
        [t or " " for t in texts], normalize_embeddings=True, batch_size=64
    ).astype(np.float32)
    return [matrix[i].tobytes() for i in range(len(texts))]


def _to_vec(b: bytes):
    np = _np()
    return np.frombuffer(b, dtype=np.float32)


def cosine(a: bytes, b: bytes) -> float:
    """Both vectors are L2-normalised by encode() so cosine == dot product."""
    np = _np()
    return float(np.dot(_to_vec(a), _to_vec(b)))


def find_nearest(
    session: Session,
    *,
    category_slug: str,
    vec: bytes,
    top_k: int = 8,
    exclude_id: int | None = None,
) -> list[tuple[Product, float]]:
    """Naive same-category scan. Instrumented so we can spot the p95 drift."""
    start = time.perf_counter()
    q = select(Product).where(
        Product.category_slug == category_slug,
        Product.embedding.is_not(None),
    )
    if exclude_id is not None:
        q = q.where(Product.id != exclude_id)
    rows = session.exec(q).all()

    if not rows:
        return []
    scored = [
        (p, cosine(vec, p.embedding))
        for p in rows
        if p.embedding is not None
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    took_ms = (time.perf_counter() - start) * 1000
    if took_ms > 100:
        logger.warning(
            "find_nearest slow: %.0fms over %d rows (category=%s)",
            took_ms,
            len(rows),
            category_slug,
        )
    return scored[:top_k]
