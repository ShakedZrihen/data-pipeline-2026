"""Store DB service — keeps the `branches` table in sync with each chain's
published store list, then fills in what that list omits.

One cycle, per chain:

    sync     newest Stores file -> parse -> upsert -> deactivate the missing
    enrich   locator page -> match by address -> write phone/hours/coordinates

The two halves are deliberately separate. The Stores file is mandated by law
and is the same shape everywhere; the locator is each chain's own website and
is a different problem per chain. A chain with no enricher yet still syncs
normally and simply keeps NULLs in the enrichment columns.

Each chain is committed on its own, and a chain that fails is logged and
skipped rather than aborting the run — one chain changing its markup should not
cost you the other three.

Expected env vars: DATABASE_URL, optionally STORES_PROVIDERS (comma-separated
subset, for running a single chain during development) and STORES_SKIP_ENRICH=1
to run the sync half alone.
"""
from __future__ import annotations

import logging
import os
import sys

from sqlalchemy import select

from base import StoreSource
from enrichers.base import Enricher
from enrichers.hazi_hinam import HaziHinamEnricher
from enrichers.rami_levi import RamiLeviEnricher
from enrichers.shufersal import ShufersalEnricher
from enrichers.yochananof import YochananofEnricher
from matching import match_stores
from repository import (
    apply_enrichment,
    deactivate_missing,
    seed_chains,
    upsert_branches,
)
from shared.db import make_engine, make_session_factory, migrate
from shared.models import Branch
from sources.hazi_hinam import HaziHinamStoreSource
from sources.rami_levi import RamiLeviStoreSource
from sources.shufersal import ShufersalStoreSource
from sources.yohananof import YohananofStoreSource

log = logging.getLogger("salim.stores")

# To add a chain: implement a StoreSource and add it here.
SOURCES: list[type[StoreSource]] = [
    YohananofStoreSource,
    RamiLeviStoreSource,
    ShufersalStoreSource,
    HaziHinamStoreSource,
]

# Optional second half, keyed by provider. All four chains are covered; the
# endpoints and their traps are in services/stores/README.md. Coverage is not
# uniform and cannot be: Yochananof publishes no phone numbers, and Shufersal's
# collection carries no opening hours at all.
ENRICHERS: dict[str, type[Enricher]] = {
    HaziHinamEnricher.name: HaziHinamEnricher,
    RamiLeviEnricher.name: RamiLeviEnricher,
    ShufersalEnricher.name: ShufersalEnricher,
    YochananofEnricher.name: YochananofEnricher,
}


def selected_sources() -> list[type[StoreSource]]:
    wanted = os.environ.get("STORES_PROVIDERS", "").strip()
    if not wanted:
        return SOURCES
    names = {n.strip() for n in wanted.split(",") if n.strip()}
    return [s for s in SOURCES if s.name in names]


_session_factory = None


def _session():
    """One session from the process-wide factory.

    ``shared/db.py`` moved from a module-level engine to factories, so the
    engine is built once here on first use rather than at import time — which
    also keeps importing this module from opening a connection.
    """
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(make_engine())
    return _session_factory()


def sync_source(source: StoreSource) -> int:
    """Bring the table in line with this chain's newest Stores file."""
    result = source.fetch()
    physical = [r for r in result.records if r.is_physical()]
    skipped = len(result.records) - len(physical)
    if skipped:
        log.info("%s: skipped %d non-branch record(s)", source.name, skipped)

    with _session() as session:
        seed_chains(session)
        written = upsert_branches(session, source.chain_id, physical)
        deactivate_missing(session, source.chain_id, {r.store_id for r in physical})
        session.commit()

    log.info("%s: %d branch(es) synced from %s", source.name, written, result.source_file)
    return written


class _Matchable:
    """A branch row in the shape `matching` expects.

    `matching` keys on `.store_id`, which is what the Stores file calls a
    branch and what this service called it before the table moved to
    `branches`. Adapting here keeps that module — the subtle part, where the
    address and name heuristics live — untouched by the rename.
    """

    __slots__ = ("store_id", "address", "name")

    def __init__(self, branch: Branch) -> None:
        self.store_id = branch.branch_id
        self.address = branch.address
        self.name = branch.name


def enrich_provider(provider: str, chain_id: str, enricher: Enricher) -> dict[str, int]:
    """Fill in phone / hours / coordinates for one chain."""
    records = enricher.fetch()

    with _session() as session:
        branches = [
            _Matchable(b)
            for b in session.scalars(
                select(Branch).where(
                    Branch.chain_id == chain_id, Branch.is_active.is_(True)
                )
            ).all()
        ]
        matches, unmatched = match_stores(branches, records)
        stats = apply_enrichment(
            session, chain_id, provider, records, matches, enricher.not_provided()
        )
        session.commit()

    missed = len(branches) - len(matches)
    if missed or unmatched:
        log.info(
            "%s: %d branch row(s) left unenriched, %d locator record(s) matched nothing",
            provider, missed, len(unmatched),
        )
    return stats


def run() -> dict[str, dict]:
    engine = make_engine()
    migrate(engine)
    global _session_factory
    _session_factory = make_session_factory(engine)
    skip_enrich = os.environ.get("STORES_SKIP_ENRICH") == "1"
    results: dict[str, dict] = {}

    for source_cls in selected_sources():
        provider = source_cls.name
        outcome = {"synced": 0, "unique": 0, "ambiguous": 0}
        try:
            outcome["synced"] = sync_source(source_cls())
        except Exception:
            log.exception("store source '%s' failed", provider)
            results[provider] = outcome
            continue

        enricher_cls = ENRICHERS.get(provider)
        if enricher_cls and not skip_enrich:
            try:
                outcome.update(
                    enrich_provider(provider, source_cls.chain_id, enricher_cls())
                )
            except Exception:
                # A locator failure must not undo a good sync.
                log.exception("enricher '%s' failed; sync kept", provider)

        results[provider] = outcome

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print("Starting the stores service...")
    totals = run()

    print(f"\n  {'provider':<12}{'branches':>10}{'enriched':>10}{'partial':>9}")
    for provider, outcome in totals.items():
        print(f"  {provider:<12}{outcome['synced']:>10}{outcome['unique']:>10}{outcome['ambiguous']:>9}")
    print(f"  {'TOTAL':<12}{sum(o['synced'] for o in totals.values()):>10}"
          f"{sum(o['unique'] for o in totals.values()):>10}"
          f"{sum(o['ambiguous'] for o in totals.values()):>9}")

    sys.exit(0 if any(o["synced"] for o in totals.values()) else 1)
