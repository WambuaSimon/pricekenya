from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, Index, LargeBinary, UniqueConstraint
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
    # Human-readable description (plain text; may span paragraphs). Scrapers
    # populate this per-merchant when the source page carries one; the first
    # scraper to see the product wins, later scrapers don't overwrite.
    description: str | None = None
    # MiniLM 384-dim float32 (1536 bytes). NULL until a scraper/CLI path
    # embeds the product; the web app never computes new embeddings.
    embedding: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
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


class LlmExtractionLog(SQLModel, table=True):
    """One row per LLM extraction attempt (Phase 0 fallback).

    Doubles as a title-hash cache: the extractor short-circuits when a recent
    successful row for the same `title_hash` exists, so the same title from N
    merchants costs one API call. Also the source-of-truth for the per-category
    daily cap check.
    """

    id: int | None = Field(default=None, primary_key=True)
    title: str
    title_hash: str = Field(index=True)  # 16-char sha256 hex prefix
    category: str = Field(index=True)
    response_json: dict | None = Field(default=None, sa_column=Column(JSON))
    parsed_ok: bool = False
    latency_ms: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (Index("ix_llm_cat_created", "category", "created_at"),)


class ProductMergeCandidate(SQLModel, table=True):
    """Two near-duplicate products flagged by the embedding merger (Phase 1).

    Written when cosine ∈ [0.90, 0.95). Below 0.90 no candidate is written;
    at or above 0.95 the auto-merge branch fires and no candidate is written
    either. Reviewer decides via /admin/merge-review.
    """

    id: int | None = Field(default=None, primary_key=True)
    source_product_id: int = Field(foreign_key="product.id", index=True)
    target_product_id: int = Field(foreign_key="product.id", index=True)
    similarity: float
    source_title: str
    source_specs: dict | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="pending", index=True)  # pending | approved | rejected
    reviewed_at: datetime | None = None
    reviewer_note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (
        UniqueConstraint("source_product_id", "target_product_id", name="uq_merge_pair"),
    )


class Review(SQLModel, table=True):
    """User-submitted rating + text review for a Product.

    Reviews are `verified_at IS NULL` (pending, invisible on the product page)
    until the reviewer clicks a magic link sent to their email — that's the
    only anti-spam gate. Aggregate rating + JSON-LD Review objects on the
    product page count only verified rows; unverified ones never render.
    Prisjakt's model is fully unverified; we add the email verification because
    Kenya has real counterfeit-review concern (CONTEXT.md §10) and the
    verification token pattern is already sitting in alerts/tokens.py.

    One review per (product, email) — someone can edit their review by
    resubmitting; a fresh magic link goes out and only re-publishes when
    they click it again.
    """

    id: int | None = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="product.id", index=True)
    email: str = Field(index=True)
    display_name: str
    rating: int  # constrained to 1..5 at the form + template level
    title: str | None = None
    body: str
    pros: str | None = None
    cons: str | None = None
    verified_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("product_id", "email", name="uq_review_product_email"),
    )


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
