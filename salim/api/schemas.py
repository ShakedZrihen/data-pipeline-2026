# Pydantic response models for the API endpoints.
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OpeningHourOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    weekday: int
    interval_index: int
    opens_at: time
    closes_at: time


class OpeningExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    interval_index: int
    is_closed: bool
    opens_at: time | None
    closes_at: time | None
    reason: str | None


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chain_id: str
    branch_id: str
    name: str | None
    city: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    timezone: str
    is_active: bool
    metadata_updated_at: datetime | None
    phone: str | None
    city_code: str | None
    store_type: str | None
    source_file: str | None
    enrichment_source: str | None
    enrichment_match: str | None
    enriched_at: datetime | None
    fields_not_provided: list[str] | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    opening_hours: list[OpeningHourOut] = Field(default_factory=list)
    opening_exceptions: list[OpeningExceptionOut] = Field(default_factory=list)


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chain_id: str
    name: str
    slug: str | None


class StoreDetailOut(StoreOut):
    branches: list[BranchOut]


class StoreListOut(BaseModel):
    items: list[StoreOut]
    total: int
    limit: int
    offset: int


class ProductOut(BaseModel):
    """A canonical, cross-chain product from ``catalog_products``."""

    model_config = ConfigDict(from_attributes=True)

    product_id: str
    gtin: str | None = None
    slug: str | None = None
    display_name: str | None = None
    manufacturer: str | None = None
    updated_at: datetime | None = None


class PriceSummaryOut(BaseModel):
    """The span of a product's current prices, so a list view needs no per-row request."""

    min_price: Decimal
    max_price: Decimal
    store_count: int
    chain_count: int


class ProductListItemOut(ProductOut):
    """A catalog product as it appears in a list, with its price span attached.

    ``price_summary`` is null when the product has no row in ``prices`` yet —
    the catalog is written from price files, but a branch's prices can arrive
    later than the product metadata.
    """

    price_summary: PriceSummaryOut | None = None


class PriceOut(BaseModel):
    """One chain SKU's current price for a product, in one store."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    chain_name: str | None = None
    store_id: str
    item_name: str | None = None
    price: Decimal
    update_time: datetime | None = None


class PromotionItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_code: str
    item_name: str | None = None
    discount_type: int | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    discount_price: Decimal | None = None
    discounted_price_per_mida: Decimal | None = None


class PromotionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    chain_name: str | None = None
    store_id: str
    promotion_id: str
    description: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    items: list[PromotionItemOut] = []


class ProductPromotionsOut(BaseModel):
    """Answers "does this product have promotions right now" plus the list itself."""

    has_promotion: bool
    promotions: list[PromotionOut]
