"""Typed, bounded helpers for S3-compatible object storage.

Supported providers are explicit: Supabase Storage, MinIO, and AWS S3. The
module refuses to infer AWS when an endpoint is missing, because that can send
project data to the wrong provider.
"""
from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypedDict, cast

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import BaseClient
from botocore.config import Config as BotoConfig


class StorageProvider(str, Enum):
    """Object-storage providers supported by this project."""

    MINIO = "minio"
    SUPABASE = "supabase"
    AWS = "aws"


class ObjectMetadata(TypedDict, total=False):
    """Metadata returned by S3 ``ListObjectsV2``."""

    Key: str
    ETag: str
    Size: int
    LastModified: datetime
    StorageClass: str


@dataclass(frozen=True)
class ObjectPage:
    """One bounded listing page and the token needed to resume after it."""

    objects: tuple[ObjectMetadata, ...]
    next_token: str | None


def _provider(value: StorageProvider | str | None) -> StorageProvider:
    raw = value or os.getenv("S3_PROVIDER")
    if not raw:
        raise ValueError("S3 provider is required; set S3_PROVIDER to minio, supabase, or aws")
    try:
        return StorageProvider(raw.lower())
    except ValueError as exc:
        choices = ", ".join(item.value for item in StorageProvider)
        raise ValueError(f"unsupported S3 provider {raw!r}; expected one of: {choices}") from exc


def get_client(
    provider: StorageProvider | str | None = None,
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    region: str | None = None,
    *,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
    total_max_attempts: int | None = None,
    retry_mode: str | None = None,
    client_config: BotoConfig | None = None,
) -> BaseClient:
    """Create an S3 client for an explicitly selected provider.

    ``client_config`` may override the generated botocore configuration. The
    timeout and retry arguments are environment-configurable for large files.
    """
    selected = _provider(provider)
    resolved_endpoint = endpoint_url or os.getenv("S3_ENDPOINT_URL") or None
    if selected in (StorageProvider.MINIO, StorageProvider.SUPABASE) and not resolved_endpoint:
        raise ValueError(f"S3_ENDPOINT_URL is required for provider {selected.value}")
    if selected is StorageProvider.AWS and resolved_endpoint:
        raise ValueError("S3_ENDPOINT_URL must be omitted for provider aws")

    resolved_access_key = access_key or os.getenv("S3_ACCESS_KEY")
    resolved_secret_key = secret_key or os.getenv("S3_SECRET_KEY")
    if bool(resolved_access_key) != bool(resolved_secret_key):
        raise ValueError("S3_ACCESS_KEY and S3_SECRET_KEY must be provided together")

    attempts = total_max_attempts or int(os.getenv("S3_TOTAL_MAX_ATTEMPTS", "3"))
    if attempts < 1:
        raise ValueError("total_max_attempts must be at least 1")

    generated_config = BotoConfig(
        connect_timeout=(
            connect_timeout
            if connect_timeout is not None
            else float(os.getenv("S3_CONNECT_TIMEOUT", "5"))
        ),
        read_timeout=(
            read_timeout if read_timeout is not None else float(os.getenv("S3_READ_TIMEOUT", "60"))
        ),
        retries={
            "total_max_attempts": attempts,
            "mode": retry_mode or os.getenv("S3_RETRY_MODE", "standard"),
        },
    )
    config = generated_config.merge(client_config) if client_config else generated_config

    return cast(
        BaseClient,
        boto3.client(
            "s3",
            endpoint_url=resolved_endpoint,
            aws_access_key_id=resolved_access_key,
            aws_secret_access_key=resolved_secret_key,
            region_name=region or os.getenv("S3_REGION"),
            config=config,
        ),
    )


def getClient(*args: Any, **kwargs: Any) -> BaseClient:  # noqa: N802
    """Compatibility alias for the public name specified in issue #30."""
    return get_client(*args, **kwargs)


def upload(
    client: BaseClient,
    bucket: str,
    source: str | Path,
    key: str | None = None,
    *,
    extra_args: Mapping[str, Any] | None = None,
    transfer_config: TransferConfig | None = None,
) -> str:
    """Upload *source* and return the object key used in *bucket*."""
    source_path = Path(source)
    object_key = key or source_path.name
    kwargs: dict[str, Any] = {}
    if extra_args is not None:
        kwargs["ExtraArgs"] = dict(extra_args)
    if transfer_config is not None:
        kwargs["Config"] = transfer_config
    client.upload_file(str(source_path), bucket, object_key, **kwargs)
    return object_key


def download(
    client: BaseClient,
    bucket: str,
    key: str,
    destination: str | Path,
    *,
    extra_args: Mapping[str, Any] | None = None,
    transfer_config: TransferConfig | None = None,
) -> Path:
    """Download *key* to *destination* and return the local path."""
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if extra_args is not None:
        kwargs["ExtraArgs"] = dict(extra_args)
    if transfer_config is not None:
        kwargs["Config"] = transfer_config
    client.download_file(bucket, key, str(destination_path), **kwargs)
    return destination_path


def iter_object_pages(
    client: BaseClient,
    bucket: str,
    prefix: str = "",
    *,
    page_size: int = 1_000,
    max_items: int | None = None,
    continuation_token: str | None = None,
) -> Iterator[ObjectPage]:
    """Yield bounded pages and resumable continuation tokens.

    ``max_items`` limits work in this scan. The last page's token can be
    persisted and passed as ``continuation_token`` in the next cycle.
    """
    if not 1 <= page_size <= 1_000:
        raise ValueError("page_size must be between 1 and 1000")
    if max_items is not None and max_items < 1:
        raise ValueError("max_items must be at least 1")

    remaining = max_items
    token = continuation_token
    while remaining is None or remaining > 0:
        max_keys = page_size if remaining is None else min(page_size, remaining)
        request: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": max_keys}
        if token:
            request["ContinuationToken"] = token

        response = client.list_objects_v2(**request)
        objects = tuple(cast(ObjectMetadata, item) for item in response.get("Contents", []))
        next_token = response.get("NextContinuationToken")
        if response.get("IsTruncated") and not next_token:
            raise RuntimeError("S3 returned a truncated page without a continuation token")

        yield ObjectPage(objects=objects, next_token=next_token)
        if remaining is not None:
            remaining -= len(objects)
        if not next_token or not response.get("IsTruncated"):
            break
        token = next_token


def iter_objects(
    client: BaseClient,
    bucket: str,
    prefix: str = "",
    **scan_options: Any,
) -> Iterator[ObjectMetadata]:
    """Lazily yield object metadata without accumulating the bucket in memory."""
    for page in iter_object_pages(client, bucket, prefix, **scan_options):
        yield from page.objects


def iter_keys(
    client: BaseClient,
    bucket: str,
    prefix: str = "",
    **scan_options: Any,
) -> Iterator[str]:
    """Lazily yield object keys using the bounded listing API."""
    for item in iter_objects(client, bucket, prefix, **scan_options):
        yield item["Key"]


def ls(client: BaseClient, bucket: str, prefix: str = "") -> list[str]:
    """Compatibility wrapper that materializes all keys; prefer ``iter_keys``."""
    return list(iter_keys(client, bucket, prefix))
