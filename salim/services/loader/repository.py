"""All writes to the price/promotion/manufacturer tables, as idempotent Postgres upserts.

Every method may be re-run on the same input (queue redelivery, crash between
commit and ack) and must converge to the same rows. Two guards make that hold:
``update_time`` from the source publication is never allowed to go backwards,
and a ``resolved`` manufacturer is never reset by a later message that
happens to lack one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, TypeVar

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from enrichment import Resolution, normalize_name
from messages import PriceMessage, PromotionMessage
from shared.models import (
    MANUFACTURER_PENDING,
    MANUFACTURER_RESOLVED,
    MANUFACTURER_UNKNOWN,
    Chain,
    Manufacturer,
    Price,
    Product,
    Promotion,
    PromotionItem,
)

T = TypeVar("T")


def _newest(messages: Iterable[T], key) -> dict:
    """Latest publication per key; within one batch the higher ``update_time`` wins, not arrival order."""
    latest: dict = {}
    for m in messages:
        k = key(m)
        current = latest.get(k)
        if current is None or (m.update_time or datetime.min.replace(tzinfo=timezone.utc)) >= (
            current.update_time or datetime.min.replace(tzinfo=timezone.utc)
        ):
            latest[k] = m
    return latest


class Repository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ prices
    def upsert_prices(self, messages: Iterable[PriceMessage], manufacturers: dict[tuple[str, str], Resolution]) -> None:
        messages = list(messages)
        by_product = _newest(messages, lambda m: (m.provider, m.item_code))
        by_price = _newest(messages, lambda m: (m.provider, m.store_id, m.item_code))
        if not by_product:
            return

        product_rows = [self._product_row(m, manufacturers.get(key)) for key, m in by_product.items()]
        stmt = insert(Product).values(product_rows)
        e = stmt.excluded
        keep_existing = Product.manufacturer_status == MANUFACTURER_RESOLVED
        incoming_resolves = e.manufacturer_status != MANUFACTURER_PENDING

        def unless_resolved(column):
            """Take the incoming value only when it answers the question and the row does not already."""
            return case((keep_existing, column), (incoming_resolves, getattr(e, column.key)), else_=column)

        stmt = stmt.on_conflict_do_update(
            index_elements=[Product.provider, Product.item_code],
            set_={
                "item_name": func.coalesce(e.item_name, Product.item_name),
                "item_type": func.coalesce(e.item_type, Product.item_type),
                "unit_quantity": func.coalesce(e.unit_quantity, Product.unit_quantity),
                "unit_of_measure": func.coalesce(e.unit_of_measure, Product.unit_of_measure),
                "quantity": func.coalesce(e.quantity, Product.quantity),
                "weighted": func.coalesce(e.weighted, Product.weighted),
                "in_package": func.coalesce(e.in_package, Product.in_package),
                "manufacturer_raw": func.coalesce(e.manufacturer_raw, Product.manufacturer_raw),
                "manufacturer": unless_resolved(Product.manufacturer),
                "manufacturer_status": unless_resolved(Product.manufacturer_status),
                "manufacturer_checked_at": unless_resolved(Product.manufacturer_checked_at),
                "updated_at": func.now(),
            },
        )
        self.session.execute(stmt)

        price_rows = [
            {"provider": m.provider, "store_id": m.store_id, "item_code": m.item_code, "price": m.price, "update_time": m.update_time}
            for m in by_price.values()
        ]
        stmt = insert(Price).values(price_rows)
        e = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[Price.provider, Price.store_id, Price.item_code],
            set_={"price": e.price, "update_time": e.update_time, "updated_at": func.now()},
            where=_not_older(Price.update_time, e.update_time),
        )
        self.session.execute(stmt)

    @staticmethod
    def _product_row(m: PriceMessage, resolution: Resolution | None) -> dict:
        if resolution is None:
            manufacturer, status, checked = None, MANUFACTURER_PENDING, None
        else:
            manufacturer = resolution.manufacturer
            status = MANUFACTURER_RESOLVED if manufacturer else MANUFACTURER_UNKNOWN
            checked = datetime.now(timezone.utc)
        return {
            "provider": m.provider,
            "item_code": m.item_code,
            "item_name": m.item_name,
            "item_type": m.item_type,
            "unit_quantity": m.unit_quantity,
            "unit_of_measure": m.unit_of_measure,
            "quantity": m.quantity,
            "weighted": m.weighted,
            "in_package": m.in_package,
            "manufacturer_raw": m.manufacturer_raw,
            "manufacturer": manufacturer,
            "manufacturer_status": status,
            "manufacturer_checked_at": checked,
        }

    # -------------------------------------------------------------- promotions
    def upsert_promotions(self, messages: Iterable[PromotionMessage]) -> None:
        for m in _newest(messages, lambda m: (m.provider, m.store_id, m.promotion_id)).values():
            self._upsert_promotion(m)

    def _upsert_promotion(self, m: PromotionMessage) -> None:
        stmt = insert(Promotion).values(
            provider=m.provider, store_id=m.store_id, promotion_id=m.promotion_id, description=m.description,
            start_time=m.start_time, end_time=m.end_time, update_time=m.update_time,
        )
        e = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=[Promotion.provider, Promotion.store_id, Promotion.promotion_id],
            set_={"description": e.description, "start_time": e.start_time, "end_time": e.end_time,
                  "update_time": e.update_time, "updated_at": func.now()},
            where=_not_older(Promotion.update_time, e.update_time),
        ).returning(Promotion.promotion_id)
        written = self.session.execute(stmt).first() is not None
        if not written:
            return  # stale publication; keep the item list we already have
        self.session.execute(
            delete(PromotionItem).where(
                PromotionItem.provider == m.provider,
                PromotionItem.store_id == m.store_id,
                PromotionItem.promotion_id == m.promotion_id,
            )
        )
        items = {i.item_code: i for i in m.items}
        if items:
            self.session.execute(
                insert(PromotionItem).values([
                    {"provider": m.provider, "store_id": m.store_id, "promotion_id": m.promotion_id,
                     "item_code": i.item_code, "discount_type": i.discount_type, "min_qty": i.min_qty,
                     "max_qty": i.max_qty, "discount_price": i.discount_price,
                     "discounted_price_per_mida": i.discounted_price_per_mida}
                    for i in items.values()
                ])
            )

    # ----------------------------------------------------------- manufacturers
    def seed_brands(self, brands: dict[str, str]) -> None:
        rows = [{"normalized_name": normalize_name(k), "manufacturer": v, "source": "dictionary"}
                for k, v in brands.items() if normalize_name(k)]
        if rows:
            self.session.execute(insert(Manufacturer).values(rows).on_conflict_do_nothing())

    def seed_chains(self, chains: dict[str, str]) -> None:
        rows = [{"chain_id": k, "name": v} for k, v in chains.items()]
        if rows:
            self.session.execute(insert(Chain).values(rows).on_conflict_do_nothing())

    def remember(self, item_name: str, manufacturer: str | None, source: str, model: str | None = None) -> None:
        """Cache one resolution; hand-entered (``manual``) rows are never overwritten."""
        key = normalize_name(item_name)
        if not key:
            return
        stmt = insert(Manufacturer).values(normalized_name=key, manufacturer=manufacturer, source=source, model=model)
        e = stmt.excluded
        self.session.execute(stmt.on_conflict_do_update(
            index_elements=[Manufacturer.normalized_name],
            set_={"manufacturer": e.manufacturer, "source": e.source, "model": e.model, "resolved_at": func.now()},
            where=Manufacturer.source != "manual",
        ))

    # ---------------------------------------------------------------- sweeper
    def pending_names(self, max_attempts: int, limit: int) -> list[str]:
        """Distinct item names still waiting for the LLM, oldest-attempted first."""
        rows = self.session.execute(
            select(Product.item_name)
            .where(
                Product.manufacturer_status == MANUFACTURER_PENDING,
                Product.manufacturer_attempts < max_attempts,
                Product.item_name.isnot(None),
            )
            .group_by(Product.item_name)
            .order_by(func.min(Product.manufacturer_attempts), Product.item_name)
            .limit(limit)
        )
        return [name for (name,) in rows]

    def apply_resolution(self, item_names: list[str], manufacturer: str | None) -> None:
        status = MANUFACTURER_RESOLVED if manufacturer else MANUFACTURER_UNKNOWN
        self.session.execute(
            update(Product)
            .where(Product.manufacturer_status == MANUFACTURER_PENDING, Product.item_name.in_(item_names))
            .values(manufacturer=manufacturer, manufacturer_status=status,
                    manufacturer_checked_at=func.now(), updated_at=func.now())
        )

    def bump_attempts(self, item_names: list[str]) -> None:
        self.session.execute(
            update(Product)
            .where(Product.manufacturer_status == MANUFACTURER_PENDING, Product.item_name.in_(item_names))
            .values(manufacturer_attempts=Product.manufacturer_attempts + 1, manufacturer_checked_at=func.now())
        )

    def mark_nameless_unknown(self) -> int:
        result = self.session.execute(
            update(Product)
            .where(Product.manufacturer_status == MANUFACTURER_PENDING, Product.item_name.is_(None))
            .values(manufacturer_status=MANUFACTURER_UNKNOWN, manufacturer_checked_at=func.now())
        )
        return result.rowcount

    def reset_attempts(self) -> int:
        return self.session.execute(
            update(Product).where(Product.manufacturer_status == MANUFACTURER_PENDING).values(manufacturer_attempts=0)
        ).rowcount

    def reset_unknown(self) -> int:
        """Re-open every ``unknown`` product (and forget its cached answer) for a fresh LLM pass."""
        self.session.execute(delete(Manufacturer).where(Manufacturer.source == "llm", Manufacturer.manufacturer.is_(None)))
        return self.session.execute(
            update(Product)
            .where(Product.manufacturer_status == MANUFACTURER_UNKNOWN)
            .values(manufacturer_status=MANUFACTURER_PENDING, manufacturer_attempts=0)
        ).rowcount

    def load_cache(self) -> dict[str, str | None]:
        rows = self.session.execute(
            select(Manufacturer.normalized_name, Manufacturer.manufacturer).where(Manufacturer.source != "dictionary")
        )
        return {name: manufacturer for name, manufacturer in rows}

    def load_brands(self) -> dict[str, str]:
        rows = self.session.execute(
            select(Manufacturer.normalized_name, Manufacturer.manufacturer).where(Manufacturer.source == "dictionary")
        )
        return {name: manufacturer for name, manufacturer in rows}


def _not_older(existing, incoming):
    """Row-level guard: only apply a publication at least as new as what is stored."""
    return (existing.is_(None)) | ((incoming.isnot(None)) & (incoming >= existing))
