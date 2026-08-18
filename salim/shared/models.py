"""SQLAlchemy models shared by the loader and api services.

``provider`` everywhere is the numeric ``ChainId`` the price-transparency XML
carries (e.g. ``7290027600007``), not a crawler name: it is what the extractor
emits, it never changes, and ``chains`` maps it to a name for display.
Chains number stores and internal items from 001, so every business key is
scoped by ``provider``.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()

MANUFACTURER_PENDING = "pending"
MANUFACTURER_RESOLVED = "resolved"
MANUFACTURER_UNKNOWN = "unknown"


class Chain(Base):
    __tablename__ = "chains"

    chain_id = Column(String(32), primary_key=True)
    name = Column(String(64), nullable=False)


class Product(Base):
    """One SKU as one chain describes it. Slowly changing; the price lives in ``prices``."""

    __tablename__ = "products"

    provider = Column(String(32), primary_key=True)
    item_code = Column(String(32), primary_key=True)

    item_name = Column(String(512))
    # 1 = barcode item (comparable across chains), 0 = chain-internal code.
    item_type = Column(Integer)
    unit_quantity = Column(String(64))
    unit_of_measure = Column(String(64))
    quantity = Column(Numeric(12, 3))
    weighted = Column(Boolean)
    in_package = Column(Numeric(12, 3))

    manufacturer = Column(String(256))
    manufacturer_raw = Column(String(256))
    manufacturer_status = Column(
        String(16), nullable=False, default=MANUFACTURER_PENDING, server_default=text("'pending'")
    )
    manufacturer_attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    manufacturer_checked_at = Column(DateTime(timezone=True))

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_products_manufacturer_status", "manufacturer_status"),)


class Price(Base):
    """Current price of one SKU in one store; older publications never overwrite newer ones."""

    __tablename__ = "prices"

    provider = Column(String(32), primary_key=True)
    store_id = Column(String(16), primary_key=True)
    item_code = Column(String(32), primary_key=True)

    price = Column(Numeric(12, 2))
    update_time = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        ForeignKeyConstraint(["provider", "item_code"], ["products.provider", "products.item_code"]),
    )


class Promotion(Base):
    __tablename__ = "promotions"

    provider = Column(String(32), primary_key=True)
    store_id = Column(String(16), primary_key=True)
    promotion_id = Column(String(32), primary_key=True)

    description = Column(String(1024))
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    update_time = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_promotions_provider_store_end", "provider", "store_id", "end_time"),)


class PromotionItem(Base):
    """Deal terms per SKU; the whole set is replaced whenever its promotion is upserted."""

    __tablename__ = "promotion_items"

    provider = Column(String(32), primary_key=True)
    store_id = Column(String(16), primary_key=True)
    promotion_id = Column(String(32), primary_key=True)
    item_code = Column(String(32), primary_key=True)

    discount_type = Column(Integer)
    min_qty = Column(Numeric(12, 3))
    max_qty = Column(Numeric(12, 3))
    discount_price = Column(Numeric(12, 2))
    discounted_price_per_mida = Column(Numeric(12, 2))

    __table_args__ = (
        ForeignKeyConstraint(
            ["provider", "store_id", "promotion_id"],
            ["promotions.provider", "promotions.store_id", "promotions.promotion_id"],
            ondelete="CASCADE",
        ),
        Index("ix_promotion_items_item", "provider", "item_code"),
    )


class Manufacturer(Base):
    """Item name -> manufacturer, keyed on the normalized name so one answer serves every chain.

    ``source`` says who answered: ``dictionary`` rows are the seeded brand
    tokens (matched by whole-token containment), ``llm`` rows are answers the
    sweeper paid for (``model`` says which), ``manual`` rows are hand
    corrections that nothing overwrites. The XML's own ManufactureName is not
    cached here; it is kept per product in ``products.manufacturer_raw``.
    """

    __tablename__ = "manufacturers"

    normalized_name = Column(String(512), primary_key=True)
    manufacturer = Column(String(256))
    source = Column(String(16), nullable=False)
    model = Column(String(64))
    resolved_at = Column(DateTime(timezone=True), server_default=func.now())
