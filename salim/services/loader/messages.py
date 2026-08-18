"""Queue message -> typed record. The one place that knows the extractor's JSON.

Both extractor outputs (``Prices.py`` and ``promotions.py``) land on the same
``raw-prices`` queue, so the shape is decided per message: a ``promotionId``
means a promotion, ``itemCode`` + ``price`` means a price item, anything else
is poison and raises ``InvalidMessage`` so the consumer can dead-letter it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


# Price-transparency files state local wall-clock times with no zone.
SOURCE_TZ = ZoneInfo("Asia/Jerusalem")


class InvalidMessage(ValueError):
    """The message cannot be loaded; requeueing would only loop."""


@dataclass(frozen=True)
class PriceMessage:
    provider: str
    store_id: str
    item_code: str
    item_name: str | None
    item_type: int | None
    manufacturer_raw: str | None
    unit_quantity: str | None
    unit_of_measure: str | None
    quantity: Decimal | None
    weighted: bool | None
    in_package: Decimal | None
    price: Decimal | None
    update_time: datetime | None


@dataclass(frozen=True)
class PromotionItemMessage:
    item_code: str
    discount_type: int | None
    min_qty: Decimal | None
    max_qty: Decimal | None
    discount_price: Decimal | None
    discounted_price_per_mida: Decimal | None


@dataclass(frozen=True)
class PromotionMessage:
    provider: str
    store_id: str
    promotion_id: str
    description: str | None
    start_time: datetime | None
    end_time: datetime | None
    update_time: datetime | None
    items: list[PromotionItemMessage] = field(default_factory=list)


def parse_message(payload: Any) -> PriceMessage | PromotionMessage:
    if not isinstance(payload, dict):
        raise InvalidMessage("message is not a JSON object")
    if payload.get("promotionId") is not None:
        return _promotion(payload)
    if payload.get("itemCode") is not None and "price" in payload:
        return _price(payload)
    raise InvalidMessage("message is neither a price item nor a promotion")


def _price(p: dict) -> PriceMessage:
    return PriceMessage(
        provider=_required(p, "superProvider"),
        store_id=_required(p, "storeId"),
        item_code=_required(p, "itemCode"),
        item_name=_text(p.get("itemName")),
        item_type=_int(p.get("itemType")),
        manufacturer_raw=_text(p.get("manufactureName")),
        unit_quantity=_text(p.get("unitQuantity")),
        unit_of_measure=_text(p.get("unitOfMeasure")),
        quantity=_decimal(p.get("quantity")),
        weighted=_bool(p.get("weighted")),
        in_package=_decimal(p.get("inPackage")),
        price=_decimal(p.get("price")),
        update_time=_timestamp(p.get("updateTime")),
    )


def _promotion(p: dict) -> PromotionMessage:
    raw_items = p.get("items") or []
    if not isinstance(raw_items, list):
        raise InvalidMessage("promotion items is not a list")
    return PromotionMessage(
        provider=_required(p, "providerId"),
        store_id=_required(p, "storeId"),
        promotion_id=_required(p, "promotionId"),
        description=_text(p.get("description")),
        start_time=_timestamp(p.get("startTime")),
        end_time=_timestamp(p.get("endTime")),
        update_time=_timestamp(p.get("updateTime")),
        items=[_promotion_item(i) for i in raw_items if isinstance(i, dict) and i.get("itemCode")],
    )


def _promotion_item(i: dict) -> PromotionItemMessage:
    return PromotionItemMessage(
        item_code=str(i["itemCode"]),
        discount_type=_int(i.get("discountType")),
        min_qty=_decimal(i.get("minQty")),
        max_qty=_decimal(i.get("maxQty")),
        discount_price=_decimal(i.get("discountPrice")),
        discounted_price_per_mida=_decimal(i.get("discountedPricePerMida")),
    )


def _required(p: dict, key: str) -> str:
    value = _text(p.get(key))
    if value is None:
        raise InvalidMessage(f"missing required field {key!r}")
    return value


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(float(value))
    except (TypeError, ValueError):
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool) or value is None:
        return value
    return str(value).strip().lower() in ("1", "true")


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=SOURCE_TZ)
