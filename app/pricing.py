"""Shared rules for deciding which prices are safe to publish a claim about.

Every "save KSh N" figure on the site is a falsifiable claim, and three
known data defects manufacture fake ones:

  1. Price concatenation. One merchant's scraper glues a was-price to a
     now-price ("63995.00" + "72995" -> 639950072995).
  2. Instalment listings. "iPhone 17 Pro Max Lipa Mdogo Mdogo" at 87,800
     is a deposit, not the price of the phone.
  3. Matcher errors. An "LG 15/8Kg Front Load Washer AND Dryer" at 238,995
     sitting inside "LG 8KG Front Washing Machine" invents a 62,995 ->
     238,995 spread that no shopper can act on.

These are display-layer guards, not fixes. The scraper, the instalment
handling and the matcher all still need repairing at the source.

Lives in its own module because the homepage (gap cards, drop rows, hero)
and the category grid have to agree on the rule. They diverged during the
2026-08 revamp and the category cards shipped a "Save up to KSh 129,000"
on a product whose real spread was a fraction of that.
"""

from __future__ import annotations

# A live offer more than this multiple of the cheapest one is treated as bad
# data rather than a bargain. Genuine spreads on this catalog run 1.3-1.6x,
# so 2x is generous.
GAP_MAX_RATIO = 2.0

# A "gap" needs this many independent quotes before it is worth showing.
GAP_MIN_MERCHANTS = 3

# Substrings marking a listing as an instalment/deposit price rather than
# the price of the product. Matched case-insensitively against
# Listing.title_on_merchant.
INSTALMENT_MARKERS = (
    "lipa mdogo",
    "deposit",
    "installment",
    "instalment",
    "per month",
)


def instalment_exclusions(listing_model):
    """NOT-LIKE clauses excluding instalment/deposit listings.

    Takes the Listing model so callers in different route modules can build
    the same filter without importing each other.
    """
    from sqlmodel import func

    return [
        ~func.lower(listing_model.title_on_merchant).contains(marker)
        for marker in INSTALMENT_MARKERS
    ]


def trusted_saving(min_price, max_price):
    """Return `max - min` when that spread is believable, else None.

    Callers render "Save up to X" only when this returns a value, so a
    product with a corrupt high price shows its cheapest price and no
    savings claim rather than a fictional one.
    """
    if min_price is None or max_price is None:
        return None
    # Prices arrive as Decimal from SQLAlchemy and GAP_MAX_RATIO is a float,
    # so the ratio test has to happen in float space — Decimal * float
    # raises TypeError. The returned value keeps its original type so the
    # `kes` filter formats it the same way as every other price.
    try:
        low, high = float(min_price), float(max_price)
    except (TypeError, ValueError):
        return None
    if high <= low or low <= 0:
        return None
    if high > GAP_MAX_RATIO * low:
        return None
    return max_price - min_price


def trim_price_outliers(offers):
    """Drop offers sitting implausibly far from the median price.

    `offers` is a list of (Listing, Merchant) tuples. Trims against the
    MEDIAN rather than the minimum, unlike trusted_saving above: that
    function compares max to min and so can only accept or reject a whole
    product, and it cannot tell which end is wrong. Observed live, the bad
    value was the MINIMUM (an iPhone 17 Pro Max at 70,000 against a
    160,000-240,000 cluster), so a min-anchored bound would have treated the
    outlier as the baseline and discarded the real prices.

    Returns the list unchanged when there are too few offers for a
    meaningful median, or when the guard would reject nearly everything —
    in that case the median itself is untrustworthy.
    """
    if len(offers) < 3:
        return offers
    prices = sorted(float(listing.price_kes) for listing, _ in offers)
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
    if median <= 0:
        return offers
    low, high = median / GAP_MAX_RATIO, median * GAP_MAX_RATIO
    kept = [o for o in offers if low <= float(o[0].price_kes) <= high]
    return kept if len(kept) >= 2 else offers
