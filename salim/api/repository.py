"""Read queries backing the API surface.

Everything here is a plain read: no writes, no schema management (that is
the loader's job -- see services/loader/repository.py). ``product_id`` is
the ``catalog_products`` id (e.g. ``gtin:729...`` or ``chain:729...:111``),
the canonical cross-chain identity described in shared/models.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import and_, distinct, func, or_, select, tuple_
from sqlalchemy.orm import Session, selectinload

from shared.models import Branch, CatalogProduct, Chain, Price, Product, Promotion, PromotionItem

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
DEFAULT_PRICE_LIMIT = 10
MAX_PRICE_LIMIT = 50
DEFAULT_STORE_LIMIT = 50
MAX_STORE_LIMIT = 100


def list_stores(
    session: Session,
    *,
    chain_id: str | None = None,
    slug: str | None = None,
    name: str | None = None,
    city: str | None = None,
    branch_name: str | None = None,
    is_active: bool | None = None,
    limit: int = DEFAULT_STORE_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    filters = []
    needs_branch_join = False

    if chain_id:
        filters.append(Chain.chain_id == chain_id)
    if slug:
        filters.append(Chain.slug == slug)
    if name:
        filters.append(Chain.name.ilike(f"%{name}%"))
    if city:
        filters.append(Branch.city.ilike(f"%{city}%"))
        needs_branch_join = True
    if branch_name:
        filters.append(Branch.name.ilike(f"%{branch_name}%"))
        needs_branch_join = True
    if is_active is not None:
        filters.append(Branch.is_active == is_active)
        needs_branch_join = True

    items_stmt = select(Chain)
    if needs_branch_join:
        items_stmt = items_stmt.join(Branch, Branch.chain_id == Chain.chain_id)
    if filters:
        items_stmt = items_stmt.where(*filters)
    items_stmt = (
        items_stmt.distinct()
        .order_by(Chain.name.asc(), Chain.chain_id.asc())
        .limit(limit)
        .offset(offset)
    )

    if needs_branch_join:
        total_stmt = (
            select(func.count(func.distinct(Chain.chain_id)))
            .select_from(Chain)
            .join(Branch, Branch.chain_id == Chain.chain_id)
        )
    else:
        total_stmt = select(func.count()).select_from(Chain)
    if filters:
        total_stmt = total_stmt.where(*filters)

    return {
        "items": list(session.execute(items_stmt).scalars().all()),
        "total": session.scalar(total_stmt) or 0,
        "limit": limit,
        "offset": offset,
    }


def get_store(session: Session, store_id: str) -> Chain | None:
    stmt = (
        select(Chain)
        .options(
            selectinload(Chain.branches).selectinload(Branch.opening_hours),
            selectinload(Chain.branches).selectinload(Branch.opening_exceptions),
        )
        .where(Chain.chain_id == store_id)
    )
    return session.execute(stmt).scalar_one_or_none()


def list_products(
    session: Session,
    *,
    q: str | None = None,
    manufacturer: str | None = None,
    has_promotion: bool | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> list[CatalogProduct]:
    """Catalog products, optionally filtered by name/slug text, manufacturer, or promotion state."""
    stmt = select(CatalogProduct)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(or_(CatalogProduct.display_name.ilike(pattern), CatalogProduct.slug.ilike(pattern)))
    if manufacturer:
        stmt = stmt.where(func.lower(CatalogProduct.manufacturer) == manufacturer.lower())
    if has_promotion is not None:
        promoted = _products_with_active_promotion()
        stmt = stmt.where(
            CatalogProduct.product_id.in_(promoted) if has_promotion else CatalogProduct.product_id.notin_(promoted)
        )
    stmt = stmt.order_by(CatalogProduct.display_name.asc().nulls_last()).limit(limit).offset(offset)
    return list(session.execute(stmt).scalars().all())


def price_summary(session: Session, product_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Cheapest and priciest current price per product, for the ids given.

    One grouped query for a whole page, rather than a prices call per row.
    Products with no priced row are absent from the result.
    """
    if not product_ids:
        return {}
    stmt = (
        select(
            Product.catalog_product_id.label("product_id"),
            func.min(Price.price).label("min_price"),
            func.max(Price.price).label("max_price"),
            # A catalog product can own several SKUs per chain, so counting
            # rows would overstate how many stores actually carry it.
            func.count(distinct(tuple_(Price.provider, Price.store_id))).label("store_count"),
            func.count(distinct(Price.provider)).label("chain_count"),
        )
        .join(Product, and_(Product.provider == Price.provider, Product.item_code == Price.item_code))
        .where(Product.catalog_product_id.in_(product_ids), Price.price.isnot(None))
        .group_by(Product.catalog_product_id)
    )
    return {row.product_id: dict(row._mapping) for row in session.execute(stmt)}


def get_product(session: Session, product_id: str) -> CatalogProduct | None:
    return session.get(CatalogProduct, product_id)


def product_prices(session: Session, product_id: str, *, order: str = "asc", limit: int = DEFAULT_PRICE_LIMIT) -> list[dict[str, Any]]:
    """The N cheapest (``order="asc"``) or priciest (``"desc"``) current prices for a product, across every chain/store."""
    stmt = (
        select(
            Price.provider,
            Chain.name.label("chain_name"),
            Price.store_id,
            Product.item_name,
            Price.price,
            Price.update_time,
        )
        .join(Product, and_(Product.provider == Price.provider, Product.item_code == Price.item_code))
        .outerjoin(Chain, Chain.chain_id == Price.provider)
        .where(Product.catalog_product_id == product_id, Price.price.isnot(None))
    )
    stmt = stmt.order_by(Price.price.asc() if order == "asc" else Price.price.desc()).limit(limit)
    return [dict(row._mapping) for row in session.execute(stmt)]


def product_promotions(session: Session, product_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
    """Promotions currently (or ever, with active_only=False) covering any SKU of this product, grouped one entry per promotion."""
    stmt = (
        select(
            Promotion.provider,
            Chain.name.label("chain_name"),
            Promotion.store_id,
            Promotion.promotion_id,
            Promotion.description,
            Promotion.start_time,
            Promotion.end_time,
            PromotionItem.item_code,
            Product.item_name,
            PromotionItem.discount_type,
            PromotionItem.min_qty,
            PromotionItem.max_qty,
            PromotionItem.discount_price,
            PromotionItem.discounted_price_per_mida,
        )
        .join(
            PromotionItem,
            and_(
                PromotionItem.provider == Promotion.provider,
                PromotionItem.store_id == Promotion.store_id,
                PromotionItem.promotion_id == Promotion.promotion_id,
            ),
        )
        .join(Product, and_(Product.provider == PromotionItem.provider, Product.item_code == PromotionItem.item_code))
        .outerjoin(Chain, Chain.chain_id == Promotion.provider)
        .where(Product.catalog_product_id == product_id)
    )
    if active_only:
        stmt = stmt.where(_active_promotion_clause())
    stmt = stmt.order_by(Promotion.end_time.asc().nulls_last())

    rows = [dict(row._mapping) for row in session.execute(stmt)]
    return _group_promotion_items(rows)


def _group_promotion_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse the one-row-per-item join back into one entry per (provider, store, promotion)."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for row in rows:
        key = (row["provider"], row["store_id"], row["promotion_id"])
        promo = grouped.get(key)
        if promo is None:
            promo = {
                "provider": row["provider"],
                "chain_name": row["chain_name"],
                "store_id": row["store_id"],
                "promotion_id": row["promotion_id"],
                "description": row["description"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "items": [],
            }
            grouped[key] = promo
            order.append(key)
        promo["items"].append(
            {
                "item_code": row["item_code"],
                "item_name": row["item_name"],
                "discount_type": row["discount_type"],
                "min_qty": row["min_qty"],
                "max_qty": row["max_qty"],
                "discount_price": row["discount_price"],
                "discounted_price_per_mida": row["discounted_price_per_mida"],
            }
        )
    return [grouped[key] for key in order]


def _products_with_active_promotion():
    """Scalar subquery of catalog_product_id values that have a live promotion right now."""
    return (
        select(Product.catalog_product_id)
        .join(PromotionItem, and_(PromotionItem.provider == Product.provider, PromotionItem.item_code == Product.item_code))
        .join(
            Promotion,
            and_(
                Promotion.provider == PromotionItem.provider,
                Promotion.store_id == PromotionItem.store_id,
                Promotion.promotion_id == PromotionItem.promotion_id,
            ),
        )
        .where(_active_promotion_clause())
        .distinct()
        .scalar_subquery()
    )


def _active_promotion_clause():
    now = datetime.now(timezone.utc)
    return and_(
        or_(Promotion.start_time.is_(None), Promotion.start_time <= now),
        or_(Promotion.end_time.is_(None), Promotion.end_time >= now),
    )
