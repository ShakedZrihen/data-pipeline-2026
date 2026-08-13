"""Writing store records into Postgres.

Two rules shape this module:

**The upsert only touches the columns its source owns.** A Stores-file run must
not blank out ``phone`` / ``city`` / coordinates / hours that the locator scrape
filled in earlier, so ``ON CONFLICT DO UPDATE`` lists the Stores-file columns
explicitly instead of replacing the whole row.

**Deactivation is only safe after a successful fetch.** ``is_active`` is derived
from presence in the newest Stores file, so a chain whose fetch failed must be
left alone entirely — otherwise one network error marks every branch of that
chain closed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from base import StoreRecord
from shared.models import Store

log = logging.getLogger("salim.stores.repository")

# Columns owned by the Stores file. Everything else on the row is owned by the
# enrichment step and is never written here.
_SOURCE_COLUMNS = ("name", "address", "city_code", "store_type", "chain_id", "source_file")


def upsert_stores(session: Session, records: list[StoreRecord]) -> int:
    """Insert or update rows for *records*. Returns the number written."""
    if not records:
        return 0

    now = datetime.now(timezone.utc)
    rows = [
        {
            "provider": r.provider,
            "store_id": r.store_id,
            "is_active": True,
            "name": r.name,
            "address": r.address,
            "city_code": r.city_code,
            "store_type": r.store_type,
            "chain_id": r.chain_id,
            "source_file": r.source_file,
            "last_seen_at": now,
        }
        for r in records
    ]

    statement = insert(Store).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[Store.provider, Store.store_id],
        set_={
            **{col: getattr(statement.excluded, col) for col in _SOURCE_COLUMNS},
            # Re-appearing in the file reactivates a branch that had closed.
            "is_active": True,
            "last_seen_at": statement.excluded.last_seen_at,
            "updated_at": now,
        },
    )
    session.execute(statement)
    log.info("upserted %d row(s)", len(rows))
    return len(rows)


def apply_enrichment(session, provider, locator_records, matches) -> dict[str, int]:
    """Write locator data onto matched store rows.

    Which fields are safe depends on how the branch matched:

    - **unique** — one store row, one locator record: write everything.
    - **ambiguous** — several store rows share one locator record, because the
      chain runs more than one business at that address (a supermarket and a
      produce store, each with its own ``StoreID``, while the locator lists the
      site once). Address-intrinsic facts still hold for both: coordinates,
      city, and the chain's phone number. **Opening hours do not** — a produce
      counter does not keep the supermarket's hours — so they are left alone
      rather than guessed at.

    Returns counts per outcome.
    """
    by_external = {r.external_id: r for r in locator_records}
    now = datetime.now(timezone.utc)
    stats = {"unique": 0, "ambiguous": 0}

    for store_id, match in matches.items():
        record = by_external.get(match.external_id)
        if record is None:
            continue

        values = {
            "city": record.city,
            "phone": record.phone,
            "latitude": record.latitude,
            "longitude": record.longitude,
            "enrichment_source": f"{provider}:{match.external_id}"[:128],
            "enrichment_match": "unique" if match.is_unique else "ambiguous",
            "enriched_at": now,
            "updated_at": now,
        }
        if match.is_unique:
            values.update(
                opening_hours=record.opening_hours,
                opening_from=record.opening_from,
                opening_to=record.opening_to,
                opening_hours_raw=(record.opening_hours_raw or None),
            )

        session.execute(
            update(Store)
            .where(Store.provider == provider, Store.store_id == store_id)
            .values(**{k: v for k, v in values.items() if v is not None})
        )
        stats["unique" if match.is_unique else "ambiguous"] += 1

    log.info(
        "%s: enriched %d row(s) uniquely, %d with address-only data",
        provider, stats["unique"], stats["ambiguous"],
    )
    return stats


def deactivate_missing(session: Session, provider: str, seen_ids: set[str]) -> int:
    """Flag branches of *provider* that the newest file no longer lists.

    Call only after that provider's fetch succeeded and returned records.
    """
    if not seen_ids:
        log.warning("refusing to deactivate %s: fetch returned no records", provider)
        return 0

    result = session.execute(
        update(Store)
        .where(
            Store.provider == provider,
            Store.store_id.not_in(seen_ids),
            Store.is_active.is_(True),
        )
        .values(is_active=False, updated_at=datetime.now(timezone.utc))
    )
    count = result.rowcount or 0
    if count:
        log.info("deactivated %d branch(es) no longer listed by %s", count, provider)
    return count
