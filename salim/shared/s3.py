"""Small shared wrapper around the S3-compatible storage API.

The same functions work with AWS S3, Supabase Storage's S3 endpoint and the
local MinIO service.  Callers provide a client explicitly to keep credentials
out of application code and to make the helpers easy to test.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config as BotoConfig


def get_client(
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    region: str | None = None,
):
    """Create an S3 client, using the project environment variables by default."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or os.getenv("S3_ENDPOINT_URL") or None,
        aws_access_key_id=access_key or os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=secret_key or os.getenv("S3_SECRET_KEY"),
        region_name=region or os.getenv("S3_REGION"),
        config=BotoConfig(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def getClient(*args, **kwargs):  # noqa: N802 - issue #30 uses this public name
    """Compatibility alias for the ``getClient`` name specified in issue #30."""
    return get_client(*args, **kwargs)


def upload(client: Any, bucket: str, source: str | Path, key: str | None = None) -> str:
    """Upload *source* and return the object key used in *bucket*."""
    source_path = Path(source)
    object_key = key or source_path.name
    client.upload_file(str(source_path), bucket, object_key)
    return object_key


def download(client: Any, bucket: str, key: str, destination: str | Path) -> Path:
    """Download *key* to *destination* and return the resulting local path."""
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(destination_path))
    return destination_path


def ls(client: Any, bucket: str, prefix: str = "") -> list[str]:
    """List every object key under *prefix*, transparently handling pagination."""
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []))
    return keys
