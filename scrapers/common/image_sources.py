"""Find a product image outside the merchant catalog — manufacturer sites only.

This is the last resort, used when no merchant we scrape can supply a working
image. It deliberately does NOT search the open web.

Why not an image search API: it always returns something. Feed it "Oppo N6A"
or "Oneplus Ce6" — titles our own parser may have invented — and it returns a
phone case, a press render or a different variant, with no signal that
distinguishes a correct hit from a wrong one. A 403 errors; a wrong image does
not. It sits next to a price looking authoritative, which on a comparison site
is worse than the honest fallback tile it replaced.

Manufacturer pages are narrow but honest: we construct a URL from the brand's
own site, and if the model does not exist there we get a 404 and propose
nothing. "No result" is the useful answer an image search can never give.

Nothing here publishes. Callers write ProductImageCandidate rows for review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urljoin

import httpx
from selectolax.parser import HTMLParser


@dataclass(frozen=True)
class Candidate:
    image_url: str
    source_url: str
    source: str


# Brand -> search endpoint on the manufacturer's own site. Each returns an
# HTML results page we read the first product link out of.
#
# Kept to brands with a real Kenyan/global storefront and a stable search URL.
# A brand that is not here simply yields no candidate, which is the correct
# outcome — better than guessing from a generic web search.
_BRAND_SEARCH: dict[str, str] = {
    "samsung": "https://www.samsung.com/africa_en/search/?searchvalue={q}",
    "xiaomi": "https://www.mi.com/global/search/?keyword={q}",
    "oppo": "https://www.oppo.com/en/search/?keyword={q}",
    "vivo": "https://www.vivo.com/en/search?q={q}",
    "realme": "https://www.realme.com/global/search?keyword={q}",
    "oneplus": "https://www.oneplus.com/global/search?query={q}",
    "infinix": "https://www.infinixmobility.com/search?q={q}",
    "tecno": "https://www.tecno-mobile.com/search/?q={q}",
    "nokia": "https://www.nokia.com/phones/en_int/search?q={q}",
    "honor": "https://www.honor.com/global/search/?q={q}",
    "google": "https://store.google.com/search?q={q}",
    "apple": "https://www.apple.com/us/search/{q}",
}

_META_IMAGE = (
    ("property", "og:image:secure_url"),
    ("property", "og:image"),
    ("name", "twitter:image"),
)

# Chrome-ish. Manufacturer sites are not the ones blocking us, but a bare
# python UA gets served degraded pages by some of them.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _og_image(html: str, base_url: str) -> str | None:
    dom = HTMLParser(html)
    for attr, val in _META_IMAGE:
        for node in dom.css(f'meta[{attr}="{val}"]'):
            content = (node.attributes.get("content") or "").strip()
            if not content:
                continue
            if content.startswith("//"):
                content = "https:" + content
            elif content.startswith("/"):
                content = urljoin(base_url, content)
            if content.startswith(("http://", "https://")):
                return content
    return None


def search_term(brand: str, title: str) -> str:
    """The model portion of `title`, with the brand stripped.

    Manufacturer search boxes expect "Galaxy A17", not "Samsung Samsung A17".
    """
    term = re.sub(rf"^\s*{re.escape(brand)}\s+", "", title, flags=re.I).strip()
    # Storage suffixes ("8/256GB") are our own annotation, not part of any
    # manufacturer's model name, and they tank the search.
    term = re.sub(r"\b\d+/\d+GB\b", "", term, flags=re.I)
    term = re.sub(r"\b\d+GB\b", "", term, flags=re.I)
    return " ".join(term.split())


async def propose(
    brand: str, title: str, *, client: httpx.AsyncClient
) -> Candidate | None:
    """One candidate image for `title`, or None. Never raises."""
    brand_key = (brand or "").strip().lower()
    template = _BRAND_SEARCH.get(brand_key)
    if not template:
        return None
    term = search_term(brand_key, title)
    if not term:
        return None

    url = template.format(q=quote_plus(term))
    try:
        resp = await client.get(
            url, headers={"User-Agent": _UA}, follow_redirects=True, timeout=20.0
        )
    except Exception:  # noqa: BLE001 — a brand site being down is not our problem
        return None
    if resp.status_code != 200:
        return None

    image = _og_image(resp.text, url)
    if not image:
        return None
    return Candidate(image_url=image, source_url=url, source=brand_key)
