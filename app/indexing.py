"""Single source of truth for "should Google index this product page?".

This module exists because the rule used to live in two places that
silently disagreed:

  - `app/routes/meta.py` decided what went into the sitemap, counting
    **all** listings on a product.
  - `app/templates/product.html` decided whether to emit `noindex`,
    counting only the **in-stock** offers `app/routes/products.py` had
    already filtered down to.

A comment in product.html claimed the two matched. They did not, and with
47% of listings out of stock the gap was enormous: on 2026-08-22 the
sitemap advertised 2,504 product URLs of which **1,175 (46.9%) served
`noindex` when Google actually fetched them** — the site asking to be
crawled and then refusing to be indexed, ~1,200 times over. That shows up
in Search Console as "Excluded by 'noindex' tag" plus an inflated
"Discovered - currently not indexed" bucket, because every wasted fetch
comes out of the same crawl budget as the pages that do deserve indexing.

The rule is now defined once, in two forms that must stay equivalent:

  - `offers_are_indexable()` — the per-page boolean, for a product whose
    in-stock offers have already been loaded.
  - `indexable_having()` — the aggregate SQL predicate, for the bulk
    sitemap query where loading every product's offers would be absurd.

`tests/test_sitemap_indexability.py` asserts the two agree; add a case
there before changing either.
"""

from __future__ import annotations

from typing import Any

# A product page earns indexing when it is a genuine *comparison* — at
# least this many DISTINCT merchants with a live offer.
#
# Distinct merchants rather than raw offer count: two in-stock listings
# from the same merchant is a duplicate SKU, not something a shopper can
# compare, and it would render as a page with two identical-looking rows.
# Measured on prod 2026-08-22, both definitions selected exactly the same
# 1,329 products, so this costs nothing today and is the stricter of the
# two as the catalog grows.
MIN_DISTINCT_MERCHANTS = 2

# Products whose every listing hasn't been re-verified within this window
# are almost certainly delisted upstream — don't advertise them to Google.
# Sitemap-only: the page itself still renders for anyone holding the link.
FRESHNESS_DAYS = 60


def offers_are_indexable(offers: list[dict[str, Any]]) -> bool:
    """True when the rendered offer list justifies indexing the page.

    `offers` is the list built by `app/routes/products.py` — already
    filtered to in-stock listings, each entry carrying a `merchant`.
    """
    return len({o["merchant"].id for o in offers}) >= MIN_DISTINCT_MERCHANTS


def indexable_having():
    """The aggregate form of `offers_are_indexable`, for a GROUP BY query.

    Caller is responsible for the two things this clause cannot express
    on its own, and both are required for equivalence:
      - grouping by `Product.id`
      - restricting the joined rows to `Listing.in_stock IS TRUE`, so the
        distinct-merchant count only sees live offers
    """
    from sqlalchemy import func

    from db.models import Listing

    return func.count(func.distinct(Listing.merchant_id)) >= MIN_DISTINCT_MERCHANTS
