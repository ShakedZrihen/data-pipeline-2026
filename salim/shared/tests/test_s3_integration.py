"""MinIO integration test for the shared S3 contract.

Run with ``docker compose --profile integration up --build --abort-on-container-exit``.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from botocore.exceptions import EndpointConnectionError

from salim.shared.s3 import download, get_client, iter_object_pages, iter_objects, upload


@skipUnless(os.getenv("MINIO_INTEGRATION_ENDPOINT"), "MinIO integration endpoint is not configured")
class MinioIntegrationTests(TestCase):
    def setUp(self):
        self.bucket = f"salim-integration-{uuid.uuid4().hex}"
        self.client = get_client(
            "minio",
            endpoint_url=os.environ["MINIO_INTEGRATION_ENDPOINT"],
            access_key=os.getenv("MINIO_INTEGRATION_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_INTEGRATION_SECRET_KEY", "minioadmin"),
            region=os.getenv("MINIO_INTEGRATION_REGION", "us-east-1"),
        )
        for attempt in range(30):
            try:
                self.client.create_bucket(Bucket=self.bucket)
                break
            except EndpointConnectionError:
                if attempt == 29:
                    raise
                time.sleep(0.5)

    def tearDown(self):
        for item in iter_objects(self.client, self.bucket):
            self.client.delete_object(Bucket=self.bucket, Key=item["Key"])
        self.client.delete_bucket(Bucket=self.bucket)

    def test_upload_paginated_listing_and_download(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected: dict[str, bytes] = {}
            for index in range(5):
                content = f"payload-{index}".encode()
                source = root / f"source-{index}.xml"
                source.write_bytes(content)
                key = f"raw/report-{index}.xml"
                upload(self.client, self.bucket, source, key)
                expected[key] = content

            pages = list(iter_object_pages(self.client, self.bucket, "raw/", page_size=2))
            self.assertEqual([len(page.objects) for page in pages], [2, 2, 1])
            self.assertIsNotNone(pages[0].next_token)
            keys = [item["Key"] for page in pages for item in page.objects]
            self.assertEqual(keys, sorted(expected))

            destination = root / "downloaded" / "report.xml"
            download(self.client, self.bucket, keys[0], destination)
            self.assertEqual(destination.read_bytes(), expected[keys[0]])
