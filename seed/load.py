"""Seed merchants + a handful of sample products and price history.

Lets the site render end-to-end before any scraping happens. Run with:
    python -m seed.load
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from db.models import Listing, Merchant, PriceHistory
from db.session import engine, init_db
from matching.match import match_or_create_product
from seed.categories import run as seed_categories

MERCHANTS = [
    {
        "slug": "jumia-ke",
        "name": "Jumia Kenya",
        "base_url": "https://www.jumia.co.ke",
    },
    {
        "slug": "kilimall-ke",
        "name": "Kilimall Kenya",
        "base_url": "https://www.kilimall.co.ke",
    },
    {
        "slug": "phoneplace-ke",
        "name": "Phone Place Kenya",
        "base_url": "https://phoneplacekenya.com",
    },
    {
        "slug": "avechi-ke",
        "name": "Avechi",
        "base_url": "https://avechi.com",
    },
    {
        "slug": "safaricom-shop",
        "name": "Safaricom Shop",
        "base_url": "https://shop.safaricom.co.ke",
    },
]

def _img(label: str, bg: str = "0f766e", fg: str = "ffffff") -> str:
    """Stable placeholder image so seed data renders the same as real scrapes."""
    return f"https://placehold.co/400x400/{bg}/{fg}/png?text={label.replace(' ', '+')}"


SAMPLE_LISTINGS = [
    # (title, image, merchant_slug, price)
    ("Tecno Spark 30C 5G 8GB+256GB Black", _img("Tecno Spark 30C"), "jumia-ke", 18999),
    ("Tecno Spark 30 C (8+256) 5G - Magic Skin Black", _img("Tecno Spark 30C"), "kilimall-ke", 17750),
    ("Tecno Spark 30C 5G 8/256GB", _img("Tecno Spark 30C"), "phoneplace-ke", 18500),
    ("Infinix Hot 50 Pro+ 8GB 256GB", _img("Infinix Hot 50 Pro+", "1e293b"), "jumia-ke", 22999),
    ("Infinix Hot 50 Pro Plus 256GB+8GB", _img("Infinix Hot 50 Pro+", "1e293b"), "kilimall-ke", 21900),
    ("Samsung Galaxy A55 5G 8GB 256GB", _img("Samsung A55", "1d4ed8"), "jumia-ke", 49999),
    ("Samsung A55 5G - 8/256GB - Awesome Navy", _img("Samsung A55", "1d4ed8"), "avechi-ke", 48500),
    ("Samsung Galaxy A55 5G 256GB 8GB RAM", _img("Samsung A55", "1d4ed8"), "safaricom-shop", 51000),
    ("Xiaomi Redmi Note 13 Pro 8+256GB", _img("Redmi Note 13 Pro", "ea580c"), "jumia-ke", 27499),
    ("Redmi Note 13 Pro 256GB 8GB", _img("Redmi Note 13 Pro", "ea580c"), "kilimall-ke", 26500),
    ("Apple iPhone 15 128GB Blue", _img("iPhone 15", "111827"), "phoneplace-ke", 134999),
    ("iPhone 15 - 128GB - Black", _img("iPhone 15", "111827"), "avechi-ke", 132500),
]


def run() -> None:
    init_db()
    seed_categories()
    with Session(engine) as session:
        # Merchants
        slug_to_merchant: dict[str, Merchant] = {}
        for m in MERCHANTS:
            existing = session.exec(select(Merchant).where(Merchant.slug == m["slug"])).first()
            if existing:
                slug_to_merchant[m["slug"]] = existing
                continue
            obj = Merchant(**m)
            session.add(obj)
            session.flush()
            slug_to_merchant[m["slug"]] = obj

        # Listings
        now = datetime.utcnow()
        for title, image_url, merchant_slug, price in SAMPLE_LISTINGS:
            product = match_or_create_product(
                session, title=title, image_url=image_url, category="phones"
            )
            if not product:
                print(f"  ! couldn't parse: {title}")
                continue
            merchant = slug_to_merchant[merchant_slug]

            listing = session.exec(
                select(Listing).where(
                    Listing.product_id == product.id,
                    Listing.merchant_id == merchant.id,
                )
            ).first()
            if listing:
                listing.price_kes = Decimal(price)
                listing.last_checked_at = now
                session.add(listing)
            else:
                listing = Listing(
                    product_id=product.id,
                    merchant_id=merchant.id,
                    url=f"{merchant.base_url}/sample/{product.slug}",
                    title_on_merchant=title,
                    price_kes=Decimal(price),
                    last_checked_at=now,
                )
                session.add(listing)
                session.flush()

            # Fabricate 30 days of price history so the chart has something to draw.
            session.exec(
                select(PriceHistory).where(PriceHistory.listing_id == listing.id)
            ).all()  # noop read just to keep session warm
            base = float(price)
            for d in range(30, -1, -1):
                jitter = random.uniform(-0.04, 0.04)
                p = round(base * (1 + jitter))
                session.add(
                    PriceHistory(
                        listing_id=listing.id,
                        price_kes=Decimal(p),
                        observed_at=now - timedelta(days=d),
                    )
                )

        session.commit()
        print("Seeded.")


if __name__ == "__main__":
    run()
