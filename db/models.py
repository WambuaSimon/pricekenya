from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


class Category(SQLModel, table=True):
    """Hierarchical category tree (e.g. Electronics → Computing → Laptops).

    parent_id = None → top-level (e.g. "electronics"). Products always attach to
    a leaf (a category whose subtree contains no other categories). Non-leaf
    categories are structural: their landing pages aggregate all descendant
    leaves' products.
    """

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    parent_id: int | None = Field(default=None, foreign_key="category.id", index=True)
    sort_order: int = 0


class Merchant(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    base_url: str
    affiliate_template: str | None = None
    logo_url: str | None = None

    listings: list["Listing"] = Relationship(back_populates="merchant")


class Product(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    canonical_key: str = Field(unique=True, index=True)
    brand: str = Field(index=True)
    model: str
    title: str
    image_url: str | None = None
    # Category leaf this product belongs to. category_slug is denormalized for
    # cheap filtering; category_id keeps referential integrity.
    category_id: int | None = Field(default=None, foreign_key="category.id", index=True)
    category_slug: str = Field(default="phones", index=True)
    # Category-specific attributes as JSON (e.g. {"storage_gb": 256, "ram_gb": 8}
    # for phones; {"screen_inches": 55, "resolution": "4K"} for TVs). The
    # matcher populates these per category.
    specs: dict | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)

    listings: list["Listing"] = Relationship(back_populates="product")


class Listing(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    merchant_id: int = Field(foreign_key="merchant.id", index=True)
    merchant_sku: str | None = None
    url: str
    title_on_merchant: str
    price_kes: Decimal
    in_stock: bool = True
    last_checked_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    product: Product | None = Relationship(back_populates="listings")
    merchant: Merchant | None = Relationship(back_populates="listings")


class PriceHistory(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    listing_id: int = Field(foreign_key="listing.id", index=True)
    price_kes: Decimal
    in_stock: bool = True
    observed_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Click(SQLModel, table=True):
    """One row per outbound click at `/out/{listing_id}`.

    Enables us to query things like "top clicked listings this week", "top
    merchants by click volume", or "click-through rate per product page view"
    once we start logging views too. Deliberately does NOT store IP, email,
    or any user identifier — the Privacy Policy commits to that.
    """

    id: int | None = Field(default=None, primary_key=True)
    listing_id: int = Field(foreign_key="listing.id", index=True)
    occurred_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    email: str = Field(index=True)
    target_price_kes: Decimal | None = None
    active: bool = True
    # Separate opt-in for non-transactional outreach (product updates, site
    # announcements). Kenya DPA + GDPR require this to be a distinct
    # consent — cannot be inferred from the alert signup itself.
    marketing_opt_in: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_notified_at: datetime | None = None
