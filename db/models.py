from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, Relationship, SQLModel


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
    storage_gb: int | None = None
    ram_gb: int | None = None
    color: str | None = None
    image_url: str | None = None
    category: str = Field(default="phone", index=True)
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


class Alert(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    email: str = Field(index=True)
    target_price_kes: Decimal | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_notified_at: datetime | None = None
