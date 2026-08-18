"""The paid tier: ask an LLM for the manufacturer of every product still ``pending``.

Runs out of band from the queue consumer (compose ``loader-enrich`` service,
or cron), so a slow or failing API never holds prices back. Nothing is sent
when nothing is pending. Each name is asked at most ``max_attempts`` times;
a failing batch is charged one attempt and ends the run, so an outage costs
one request per run rather than one per name.

    python enrich.py --backfill                 # resolve pending products
    python enrich.py --backfill --batch-size 50 --max-attempts 3
    python enrich.py --reset-attempts           # allow exhausted names another try
    python enrich.py --reset-unknown            # forget "no manufacturer" answers and re-ask
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import sessionmaker

from enrichment import normalize_name
from repository import Repository

log = logging.getLogger("salim.loader.enrich")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_ATTEMPTS = 3

SYSTEM_PROMPT = (
    "You extract the manufacturer or brand from Israeli supermarket product names. "
    "Names are mostly Hebrew, sometimes English, and mix product type, brand, size and flavour in no fixed order. "
    "For each item return the manufacturer or brand exactly as it appears in the name, in its original language, "
    "without size, flavour, percentage or packaging words. "
    "If the name contains no manufacturer or brand, return null. Do not guess and do not add knowledge that is not "
    "in the name. Return one result per input id."
)

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "manufacturer": {"type": ["string", "null"]}},
                "required": ["id", "manufacturer"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


class Resolver(Protocol):
    model: str

    def resolve(self, batch: list[tuple[int, str]]) -> dict[int, str | None]: ...


class LlmResolver:
    """One Messages call per batch; structured output keeps parsing trivial."""

    def __init__(self, client, model: str = DEFAULT_MODEL):
        self.client = client
        self.model = model

    def resolve(self, batch: list[tuple[int, str]]) -> dict[int, str | None]:
        items = [{"id": i, "name": name} for i, name in batch]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
            output_config={"format": {"type": "json_schema", "schema": RESULT_SCHEMA}},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("model refused the request")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise RuntimeError(f"no text block in response (stop_reason={response.stop_reason})")
        answers: dict[int, str | None] = {}
        for row in json.loads(text)["results"]:
            value = row.get("manufacturer")
            value = value.strip() if isinstance(value, str) else None
            answers[int(row["id"])] = value or None
        return answers


@dataclass
class BackfillStats:
    resolved: int = 0
    unknown: int = 0
    failed: int = 0
    from_cache: int = 0


def run_backfill(
    sessions: sessionmaker,
    resolver: Resolver,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> BackfillStats:
    stats = BackfillStats()
    with sessions() as session:
        repo = Repository(session)
        nameless = repo.mark_nameless_unknown()
        cache = repo.load_cache()
        session.commit()
    stats.unknown += nameless

    while True:
        with sessions() as session:
            repo = Repository(session)
            names = repo.pending_names(max_attempts, limit=batch_size)
            if not names:
                break
            groups: dict[str, list[str]] = {}
            for name in names:
                groups.setdefault(normalize_name(name), []).append(name)

            to_ask: list[tuple[int, str]] = []
            keys: list[str] = []
            for key, raw_names in groups.items():
                if key in cache:
                    repo.apply_resolution(raw_names, cache[key])
                    stats.from_cache += 1
                    _count(stats, cache[key])
                else:
                    keys.append(key)
                    to_ask.append((len(keys) - 1, raw_names[0]))

            if to_ask:
                try:
                    answers = resolver.resolve(to_ask)
                except Exception as exc:  # noqa: BLE001 - any API failure ends the run
                    log.warning("LLM batch of %d failed: %s", len(to_ask), exc)
                    repo.bump_attempts([n for key in keys for n in groups[key]])
                    stats.failed += len(to_ask)
                    session.commit()
                    return stats
                for idx, key in enumerate(keys):
                    raw_names = groups[key]
                    if idx not in answers:
                        repo.bump_attempts(raw_names)
                        stats.failed += 1
                        continue
                    manufacturer = answers[idx]
                    repo.apply_resolution(raw_names, manufacturer)
                    repo.remember(raw_names[0], manufacturer, source="llm", model=resolver.model)
                    cache[key] = manufacturer
                    _count(stats, manufacturer)
            session.commit()
        log.info("backfill progress: %s", stats)
    return stats


def _count(stats: BackfillStats, manufacturer: str | None) -> None:
    if manufacturer:
        stats.resolved += 1
    else:
        stats.unknown += 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backfill", action="store_true", help="resolve pending products via the LLM")
    parser.add_argument("--reset-attempts", action="store_true")
    parser.add_argument("--reset-unknown", action="store_true")
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("ENRICHER_BATCH_SIZE", DEFAULT_BATCH_SIZE)))
    parser.add_argument("--max-attempts", type=int, default=int(os.environ.get("ENRICHER_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)))
    args = parser.parse_args(argv)
    if not (args.backfill or args.reset_attempts or args.reset_unknown):
        parser.error("nothing to do; pass --backfill, --reset-attempts and/or --reset-unknown")

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from shared.db import init_db, make_engine, make_session_factory

    engine = make_engine()
    init_db(engine)
    sessions = make_session_factory(engine)

    if args.reset_attempts or args.reset_unknown:
        with sessions() as session:
            repo = Repository(session)
            if args.reset_attempts:
                log.info("reset attempts on %d pending products", repo.reset_attempts())
            if args.reset_unknown:
                log.info("re-opened %d unknown products", repo.reset_unknown())
            session.commit()

    if args.backfill:
        import anthropic

        resolver = LlmResolver(anthropic.Anthropic(), model=os.environ.get("ENRICHER_MODEL", DEFAULT_MODEL))
        stats = run_backfill(sessions, resolver, batch_size=args.batch_size, max_attempts=args.max_attempts)
        log.info("backfill done: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
