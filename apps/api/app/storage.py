"""Private S3 access for attachments.

The worker has its own copy of the download side; the two services are built and
deployed as separate images, so this module only carries what the API needs.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import (
    DOWNLOAD_URL_EXPIRY_SECONDS,
    UPLOAD_URL_EXPIRY_SECONDS,
    StorageSettings,
    load_storage_settings,
)

# S3 reports a missing object as either of these, depending on the call
_MISSING_CODES: Final = ("404", "NoSuchKey", "NotFound")


class StorageUnavailable(Exception):
    """The bucket is not configured or S3 rejected the call."""


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    size: int | None
    content_type: str | None
    etag: str | None


@lru_cache(maxsize=None)
def s3_client(settings: StorageSettings) -> Any:
    """Build the client once per configuration; credentials resolve per request."""
    return boto3.client(
        "s3", region_name=settings.region, endpoint_url=settings.endpoint_url
    )


def _s3(settings: StorageSettings, client: Any | None) -> Any:
    return client or s3_client(settings)


def _bucket(settings: StorageSettings) -> str:
    if not settings.bucket:
        raise StorageUnavailable("S3_BUCKET_NAME is not configured")
    return settings.bucket


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def presign_upload(
    key: str,
    content_type: str,
    *,
    expires_in: int = UPLOAD_URL_EXPIRY_SECONDS,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> str:
    """A short-lived PUT URL with the content type signed into it."""
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        return _s3(settings, client).generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable(str(exc)) from exc


def presign_download(
    key: str,
    *,
    expires_in: int = DOWNLOAD_URL_EXPIRY_SECONDS,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> str:
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        return _s3(settings, client).generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable(str(exc)) from exc


def head_object(
    key: str,
    *,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> StoredObject | None:
    """Describe an object; None when it is not there."""
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        response = _s3(settings, client).head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if _error_code(exc) in _MISSING_CODES:
            return None
        raise StorageUnavailable(str(exc)) from exc
    except BotoCoreError as exc:
        raise StorageUnavailable(str(exc)) from exc

    return StoredObject(
        bucket=bucket,
        key=key,
        size=response.get("ContentLength"),
        content_type=response.get("ContentType"),
        etag=response.get("ETag", "").strip('"') or None,
    )


def read_prefix(
    key: str,
    *,
    length: int = 8,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> bytes:
    """The first bytes of an object, so a signature can be checked cheaply."""
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        response = _s3(settings, client).get_object(
            Bucket=bucket, Key=key, Range=f"bytes=0-{max(0, length - 1)}"
        )
        body = response["Body"]
        return body.read(length)
    except (BotoCoreError, ClientError, KeyError) as exc:
        raise StorageUnavailable(str(exc)) from exc


def copy_object(
    source_key: str,
    target_key: str,
    *,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> None:
    """Server-side copy; file bytes never pass through the API."""
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        _s3(settings, client).copy_object(
            Bucket=bucket,
            Key=target_key,
            CopySource={"Bucket": bucket, "Key": source_key},
            MetadataDirective="COPY",
        )
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable(str(exc)) from exc


def delete_object(
    key: str,
    *,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> None:
    """Delete an object. S3 treats a missing key as success."""
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    try:
        _s3(settings, client).delete_object(Bucket=bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable(str(exc)) from exc
