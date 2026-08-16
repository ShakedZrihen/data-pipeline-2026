import json
import unittest
from unittest.mock import MagicMock, patch

from salim.shared.rabbitmq import RabbitMQClient


class TestRabbitMQClient(unittest.TestCase):

    @patch("salim.shared.rabbitmq.pika.BlockingConnection")
    def test_upload_json_message(self, mock_connection_class):
        connection = MagicMock()
        channel = MagicMock()

        mock_connection_class.return_value = connection
        connection.channel.return_value = channel

        client = RabbitMQClient(
            url="amqp://guest:guest@localhost:5672/",
            queue="test-queue",
        )

        data = {
            "itemCode": "123",
            "price": 9.9,
        }

        client.upload(data)

        channel.queue_declare.assert_called_once_with(
            queue="test-queue",
            durable=True,
        )

        args = channel.basic_publish.call_args.kwargs

        self.assertEqual(args["exchange"], "")
        self.assertEqual(args["routing_key"], "test-queue")
        self.assertEqual(
            json.loads(args["body"].decode("utf-8")),
            data,
        )

        connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()