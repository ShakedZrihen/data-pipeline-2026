from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any

import pika


class RabbitMQClient:
    def __init__(
        self,
        url: str | None = None,
        queue: str | None = None,
    ):
        self.url = url or os.environ.get(
            "RABBITMQ_URL",
            "amqp://guest:guest@localhost:5672/",
        )
        self.queue = queue or os.environ.get(
            "RABBITMQ_QUEUE",
            "raw-prices",
        )

    def _connect(self) -> pika.BlockingConnection:
        return pika.BlockingConnection(
            pika.URLParameters(self.url)
        )

    def upload(self, data: Any) -> None:
        self.upload_many([data])

    def upload_many(self, records: Iterable[Any]) -> None:
        connection = self._connect()

        try:
            channel = connection.channel()

            channel.queue_declare(
                queue=self.queue,
                durable=True,
            )

            for record in records:
                body = json.dumps(
                    record,
                    ensure_ascii=False,
                ).encode("utf-8")

                channel.basic_publish(
                    exchange="",
                    routing_key=self.queue,
                    body=body,
                    properties=pika.BasicProperties(
                        content_type="application/json",
                        delivery_mode=2,
                    ),
                )
        finally:
            connection.close()