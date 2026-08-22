"""Write ProductRedirect rows whenever a Product is deleted by a merge.

The rule this module exists to enforce: **no code path may delete a
Product without first recording where its slug went.** Every deletion is
a URL Google has probably indexed; deleting without a redirect turns it
into a permanent 404 and throws away whatever link equity it accrued.

That rule was documented (see the ProductRedirect model docstring) but
only ever honoured by `scripts/coarsen_phones_backfill.py`. The two other
paths that delete products — the `/admin/merge-review` approve handler
and `scripts/normalize_products.py` — did not, so the prod table sat at
**0 rows** while GSC reported **93 "Not found (404)"**. The 301 fallback
in `app/routes/products.py` was querying an empty table on every 404.

`record_redirect` is the chain-collapsing implementation, lifted here
from the backfill script so all three callers share one behaviour.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlmodel import Session

from db.models import ProductRedirect


def record_redirect(session: Session, *, old_slug: str, new_slug: str) -> None:
    """Point `old_slug` at `new_slug`, collapsing any chain through it.

    Before: A → B, then B is merged into C.
    Without chain-collapse: A → B (stale, B is gone) — the redirect breaks
    and the visitor holding A gets a 404 anyway.
    With chain-collapse: A → C is rewritten alongside B → C in one call,
    so every mapping stays at most one hop.

    Idempotent — re-running a merge that already registered the same
    mapping is a no-op. Self-redirects are refused: a slug pointing at
    itself would make `product_detail` bounce a 404 into a redirect loop.

    Does not commit; the caller owns the transaction so the redirect and
    the deletion that motivated it land atomically.
    """
    if old_slug == new_slug:
        return

    # Rewrite chains: anything currently pointing at old_slug should now
    # point at new_slug.
    session.execute(
        update(ProductRedirect)
        .where(ProductRedirect.new_slug == old_slug)
        .values(new_slug=new_slug)
    )
    existing = session.get(ProductRedirect, old_slug)
    if existing:
        existing.new_slug = new_slug
        session.add(existing)
    else:
        session.add(ProductRedirect(old_slug=old_slug, new_slug=new_slug))

    # If new_slug was itself a redirect source, the chain rewrite above
    # could have produced new_slug → new_slug. Drop it rather than serve
    # a self-referential 301.
    self_ref = session.get(ProductRedirect, new_slug)
    if self_ref is not None and self_ref.new_slug == new_slug:
        session.delete(self_ref)
