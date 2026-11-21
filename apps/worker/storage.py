"""Read-only S3 access for attachments the API already confirmed.

The worker never uploads: the API hands the browser a presigned PUT, and only
downloads from the private bucket happen here.
"""

from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from settings import StorageSettings, load_storage_settings


class StorageUnavailable(Exception):
    """The bucket is not configured or S3 rejected the call."""


class ObjectTooLarge(Exception):
    """The object exceeds the size this process will read into memory."""


@lru_cache(maxsize=None)
def s3_client(settings: StorageSettings) -> Any:
    """Build the client once per configuration; credentials resolve per request."""
    return boto3.client(
        "s3", region_name=settings.region, endpoint_url=settings.endpoint_url
    )


def _s3(settings: StorageSettings, client: Any | None) -> Any:
    """The injected client in a test, otherwise the cached one for this config."""
    return client or s3_client(settings)


def _bucket(settings: StorageSettings) -> str:
    if not settings.bucket:
        raise StorageUnavailable("S3_BUCKET_NAME is not configured")
    return settings.bucket


def read_object(
    key: str,
    *,
    max_bytes: int,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> bytes:
    """Read an object into memory, refusing one larger than the upload limit."""
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        response = _s3(settings, client).get_object(Bucket=bucket, Key=key)
        data = response["Body"].read(max_bytes + 1)
    except (BotoCoreError, ClientError, KeyError) as exc:
        raise StorageUnavailable(str(exc)) from exc

    if len(data) > max_bytes:
        raise ObjectTooLarge("object is larger than the attachment limit")
    return data
