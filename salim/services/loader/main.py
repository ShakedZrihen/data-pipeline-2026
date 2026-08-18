"""Loader service: consume the raw-prices queue in batches and upsert into Postgres.

Delivery is at-least-once and every write is an idempotent upsert, so the
ack rule is simply: commit first, ack after. Messages that can never load
(bad JSON, unknown shape) are copied to ``<queue>.dlq`` and acked, so they
can be inspected without blocking the queue; any other failure nacks the
whole batch back for redelivery.

Expected env vars: RABBITMQ_URL, RABBITMQ_QUEUE, DATABASE_URL.
Optional: LOADER_BATCH_SIZE (200), LOADER_BATCH_WAIT_SECONDS (2),
LOADER_CACHE_REFRESH_SECONDS (600), LOG_LEVEL.
"""
from __future__ import annotations

import logging
import os
import time

import pika
from pika.adapters.blocking_connection import BlockingChannel

from brands import BRANDS
from chains import CHAINS
from consumer import BatchProcessor
from enrichment import BrandDictionary
from repository import Repository
from shared.db import init_db, make_engine, make_session_factory

log = logging.getLogger("salim.loader")

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
QUEUE = os.environ.get("RABBITMQ_QUEUE", "raw-prices")
DLQ = f"{QUEUE}.dlq"
BATCH_SIZE = int(os.environ.get("LOADER_BATCH_SIZE", "200"))
BATCH_WAIT_SECONDS = float(os.environ.get("LOADER_BATCH_WAIT_SECONDS", "2"))
# The sweeper writes new manufacturer answers behind the consumer's back.
CACHE_REFRESH_SECONDS = float(os.environ.get("LOADER_CACHE_REFRESH_SECONDS", "600"))
RECONNECT_DELAY_SECONDS = 5


def build_processor(sessions) -> BatchProcessor:
    with sessions() as session:
        repo = Repository(session)
        repo.seed_chains(CHAINS)
        repo.seed_brands(BRANDS)
        session.commit()
        brands = BrandDictionary(repo.load_brands())
        cache = repo.load_cache()
    log.info("loaded %d brands, %d cached names", len(BRANDS), len(cache))
    return BatchProcessor(sessions, brands, cache)


def consume_forever(processor: BatchProcessor) -> None:
    while True:
        try:
            _consume(processor)
        except pika.exceptions.AMQPError as exc:
            log.warning("RabbitMQ connection or channel failed (%s); reconnecting in %ss", exc, RECONNECT_DELAY_SECONDS)
            time.sleep(RECONNECT_DELAY_SECONDS)


def _consume(processor: BatchProcessor) -> None:
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue=QUEUE, durable=True)
    channel.queue_declare(queue=DLQ, durable=True)
    channel.basic_qos(prefetch_count=BATCH_SIZE)
    log.info("consuming %s (batch %d, wait %.1fs)", QUEUE, BATCH_SIZE, BATCH_WAIT_SECONDS)

    batch: list[tuple[int, bytes]] = []
    cache_refreshed_at = time.monotonic()
    for method, _properties, body in channel.consume(QUEUE, inactivity_timeout=BATCH_WAIT_SECONDS):
        if method is not None:
            batch.append((method.delivery_tag, body))
        if batch and (method is None or len(batch) >= BATCH_SIZE):
            _handle_batch(channel, processor, batch)
            batch = []
        if time.monotonic() - cache_refreshed_at > CACHE_REFRESH_SECONDS:
            processor.refresh_cache()
            cache_refreshed_at = time.monotonic()


def _handle_batch(channel: BlockingChannel, processor: BatchProcessor, batch: list[tuple[int, bytes]]) -> None:
    last_tag = batch[-1][0]
    try:
        result = processor.process(batch)
    except Exception:  # noqa: BLE001 - DB down, bad state: hand the batch back and keep running
        log.exception("batch of %d failed; requeueing", len(batch))
        channel.basic_nack(delivery_tag=last_tag, multiple=True, requeue=True)
        time.sleep(RECONNECT_DELAY_SECONDS)
        return
    bodies = dict(batch)
    for tag, reason in result.poison:
        log.warning("dead-lettering message %d: %s", tag, reason)
        channel.basic_publish(
            exchange="",
            routing_key=DLQ,
            body=bodies[tag],
            properties=pika.BasicProperties(delivery_mode=2, headers={"x-reason": reason[:200]}),
        )
    channel.basic_ack(delivery_tag=last_tag, multiple=True)


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("pika").setLevel(logging.WARNING)
    engine = make_engine()
    init_db(engine)
    processor = build_processor(make_session_factory(engine))
    consume_forever(processor)


if __name__ == "__main__":
    main()
