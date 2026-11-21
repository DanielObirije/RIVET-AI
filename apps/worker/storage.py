"""S3 asset storage, ready for generated files that do not exist yet.

Nothing in the chat flow produces an asset, so nothing calls this from the job
path. It is here so a future image, PDF or document feature has one place to
upload, look up, sign and delete objects, with the bucket coming from config.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from settings import StorageSettings, load_storage_settings

logger = logging.getLogger(__name__)

DEFAULT_EXPIRY_SECONDS: Final = 3600
# S3 reports a missing object as either of these, depending on the call
_MISSING_CODES: Final = ("404", "NoSuchKey", "NotFound")


class StorageUnavailable(Exception):
    """The bucket is not configured or S3 rejected the call."""


@dataclass(frozen=True)
class StoredAsset:
    """What to keep in PostgreSQL: the key plus enough to serve it later."""

    bucket: str
    key: str
    size: int | None = None
    content_type: str | None = None
    etag: str | None = None


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


def _error_code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def upload_asset(
    key: str,
    data: bytes,
    *,
    content_type: str | None = None,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> StoredAsset:
    """Upload bytes and return the metadata a job row should keep.

    No ACL is sent: the bucket policy decides who may read, and a private
    bucket stays private. Downloads go through presigned URLs instead.
    """
    settings = settings or load_storage_settings()
    bucket = _bucket(settings)
    kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": data}
    if content_type:
        kwargs["ContentType"] = content_type

    try:
        response = _s3(settings, client).put_object(**kwargs)
    except (BotoCoreError, ClientError) as exc:
        raise StorageUnavailable(str(exc)) from exc

    return StoredAsset(
        bucket=bucket,
        key=key,
        size=len(data),
        content_type=content_type,
        etag=response.get("ETag", "").strip('"') or None,
    )


def asset_metadata(
    key: str,
    *,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> StoredAsset | None:
    """Head the object; None when it is not there."""
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

    return StoredAsset(
        bucket=bucket,
        key=key,
        size=response.get("ContentLength"),
        content_type=response.get("ContentType"),
        etag=response.get("ETag", "").strip('"') or None,
    )


def delete_asset(
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


def asset_download_url(
    key: str,
    *,
    expires_in: int = DEFAULT_EXPIRY_SECONDS,
    settings: StorageSettings | None = None,
    client: Any | None = None,
) -> str:
    """A time-limited URL for a private object."""
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
