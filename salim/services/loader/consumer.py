"""Turns a batch of raw queue bodies into one DB transaction.

A body that can never load is reported as poison rather than raised, so it
cannot hold up the good ones: bad JSON and unknown shapes are caught up
front, and if Postgres rejects a row (a value too long for its column) the
batch is retried one message at a time to find the culprit. Anything else,
such as the database being unreachable, propagates so the caller can requeue.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import sessionmaker

from enrichment import BrandDictionary, Resolution, resolve_free
from messages import InvalidMessage, PriceMessage, PromotionMessage, parse_message
from repository import Repository

log = logging.getLogger("salim.loader.consumer")

Message = PriceMessage | PromotionMessage


@dataclass
class BatchResult:
    loaded: list[int] = field(default_factory=list)
    poison: list[tuple[int, str]] = field(default_factory=list)


class BatchProcessor:
    def __init__(self, sessions: sessionmaker, brands: BrandDictionary, cache: dict[str, str | None]):
        self.sessions = sessions
        self.brands = brands
        self.cache = cache

    def refresh_cache(self) -> None:
        """Pick up answers the sweeper wrote since startup."""
        with self.sessions() as session:
            self.cache = Repository(session).load_cache()

    def process(self, bodies: Iterable[tuple[int, bytes]]) -> BatchResult:
        result = BatchResult()
        parsed: list[tuple[int, Message]] = []
        for tag, body in bodies:
            try:
                parsed.append((tag, parse_message(json.loads(body))))
            except (InvalidMessage, ValueError, UnicodeDecodeError) as exc:
                result.poison.append((tag, str(exc)))
        if not parsed:
            return result

        try:
            self._write([m for _, m in parsed])
            result.loaded.extend(tag for tag, _ in parsed)
        except (DataError, IntegrityError) as exc:
            log.warning("batch rejected by the database (%s); isolating the offending message", exc.orig)
            for tag, message in parsed:
                try:
                    self._write([message])
                    result.loaded.append(tag)
                except (DataError, IntegrityError) as row_exc:
                    result.poison.append((tag, str(row_exc.orig)))
        log.info("loaded %d messages, %d poison", len(result.loaded), len(result.poison))
        return result

    def _write(self, messages: list[Message]) -> None:
        prices = [m for m in messages if isinstance(m, PriceMessage)]
        promotions = [m for m in messages if isinstance(m, PromotionMessage)]
        with self.sessions() as session:
            repo = Repository(session)
            repo.upsert_prices(prices, self._resolve(prices))
            repo.upsert_promotions(promotions)
            session.commit()

    def _resolve(self, prices: list[PriceMessage]) -> dict[tuple[str, str], Resolution]:
        resolved: dict[tuple[str, str], Resolution] = {}
        for m in prices:
            hit = resolve_free(m.item_name, m.manufacturer_raw, self.cache, self.brands)
            if hit is not None:
                resolved[(m.provider, m.item_code)] = hit
        return resolved
