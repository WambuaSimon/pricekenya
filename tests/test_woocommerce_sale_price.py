"""A discounted WooCommerce listing must be stored at the price you pay.

WooCommerce renders both prices on a sale item, `<del>` (before) then
`<ins>` (now). The card selector used to try `.price bdi` first, which
matches the first bdi in document order — the one inside `<del>` — so the
`.price ins bdi` branch was unreachable and every sale item across every WC
merchant was stored at its pre-sale price.

That is the dangerous direction to be wrong in: we advertised 18,995 for a
listing that actually charged 14,995, so the merchant looked more expensive
than it was and could lose the comparison it should have won.
"""

from __future__ import annotations

from decimal import Decimal

from selectolax.parser import HTMLParser

from scrapers.common.woocommerce import _extract_product

BASE = "https://example.co.ke"


def _card(price_html: str) -> object:
    html = f"""
    <li class="product">
      <a href="/product/thing/">
        <img src="{BASE}/img.jpg" alt="Thing">
        <h2 class="woocommerce-loop-product__title">Hisense Soundbar 3.1CH</h2>
        {price_html}
      </a>
    </li>
    """
    return HTMLParser(html).css_first("li.product")


def _price_of(price_html: str) -> Decimal | None:
    listing = _extract_product(_card(price_html), BASE, "example-ke", "audio")
    return listing.price_kes if listing else None


# Exactly the markup smartdeviceskenya.co.ke serves on a discounted soundbar,
# screen-reader spans included — those carry a second copy of each figure and
# would poison a naive text-scrape of the whole .price element.
SALE = """
<span class="price">
  <del aria-hidden="true"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">KSh</span>18,995.00</bdi></span></del>
  <span class="screen-reader-text">Original price was: KSh18,995.00.</span>
  <ins aria-hidden="true"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">KSh</span>14,995.00</bdi></span></ins>
  <span class="screen-reader-text">Current price is: KSh14,995.00.</span>
</span>
"""

PLAIN = """
<span class="price"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">KSh</span>17,500.00</bdi></span></span>
"""

# Some themes drop <bdi> and leave only .amount inside <ins>.
SALE_NO_BDI = """
<span class="price">
  <del><span class="woocommerce-Price-amount amount">KSh18,995.00</span></del>
  <ins><span class="woocommerce-Price-amount amount">KSh14,995.00</span></ins>
</span>
"""


def test_sale_item_uses_the_discounted_price():
    assert _price_of(SALE) == Decimal("14995")


def test_sale_item_without_bdi_uses_the_discounted_price():
    assert _price_of(SALE_NO_BDI) == Decimal("14995")


def test_undiscounted_item_is_unaffected():
    assert _price_of(PLAIN) == Decimal("17500")


def test_price_range_takes_the_low_end():
    """"KSh 12,000 – KSh 15,000" variants: the low end is what the card
    advertises and what the shopper expects to see in a comparison."""
    ranged = (
        '<span class="price"><span class="woocommerce-Price-amount amount">'
        "<bdi>KSh12,000.00</bdi></span> – <span class="
        '"woocommerce-Price-amount amount"><bdi>KSh15,000.00</bdi></span></span>'
    )
    assert _price_of(ranged) == Decimal("12000")
