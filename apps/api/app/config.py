import os
from dataclasses import dataclass
from typing import Final

DEFAULT_ALLOWED_ORIGINS = "http://localhost:3000"
# the worker computes the same default; DATABASE_URL overrides it
DEFAULT_DATABASE_URL: Final = "postgresql://rivet:rivet@localhost:5432/rivet"
# boto3 needs a region to build a client; AWS_REGION overrides it
DEFAULT_AWS_REGION: Final = "us-east-1"
# matches apps/worker/settings.py; RDS limits the total across processes, so
# both numbers are env-overridable
DEFAULT_POOL_MIN_SIZE: Final = 1
DEFAULT_POOL_MAX_SIZE: Final = 8
DEFAULT_MAX_UPLOAD_SIZE_MB: Final = 1
DEFAULT_PENDING_UPLOAD_TTL_HOURS: Final = 24
# short enough that a leaked URL is not a lasting grant
UPLOAD_URL_EXPIRY_SECONDS: Final = 300
DOWNLOAD_URL_EXPIRY_SECONDS: Final = 300


@dataclass(frozen=True)
class Settings:
    allowed_origins: tuple[str, ...]


@dataclass(frozen=True)
class SqsSettings:
    """Where to publish jobs. A missing queue URL is a misconfiguration, not a default."""

    queue_url: str | None
    region: str
    endpoint_url: str | None


@dataclass(frozen=True)
class StorageSettings:
    """Where attachments go. A missing bucket only fails on first use."""

    bucket: str | None
    region: str
    endpoint_url: str | None


def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None


def pool_sizes() -> tuple[int, int]:
    """Connections one process keeps open (min) and may open at peak (max)."""
    min_size = _int("DB_POOL_MIN_SIZE", DEFAULT_POOL_MIN_SIZE)
    max_size = _int("DB_POOL_MAX_SIZE", DEFAULT_POOL_MAX_SIZE)
    if min_size < 0 or max_size < 1 or min_size > max_size:
        raise ValueError(
            f"DB_POOL_MIN_SIZE ({min_size}) and DB_POOL_MAX_SIZE ({max_size})"
            " must satisfy 0 <= min <= max"
        )
    return min_size, max_size


def load_settings() -> Settings:
    origins = os.getenv("CORS_ALLOWED_ORIGINS") or DEFAULT_ALLOWED_ORIGINS
    return Settings(
        allowed_origins=tuple(
            origin.strip() for origin in origins.split(",") if origin.strip()
        ),
    )


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip() or DEFAULT_DATABASE_URL


def load_sqs_settings() -> SqsSettings:
    """Read the queue configuration on each call, so env changes need no restart.

    `endpoint_url` exists for LocalStack and is empty in production, where boto3
    talks to the regional SQS endpoint.
    """
    return SqsSettings(
        queue_url=(os.getenv("SQS_QUEUE_URL") or "").strip() or None,
        region=(os.getenv("AWS_REGION") or "").strip() or DEFAULT_AWS_REGION,
        endpoint_url=(os.getenv("SQS_ENDPOINT_URL") or "").strip() or None,
    )


def load_storage_settings() -> StorageSettings:
    return StorageSettings(
        bucket=(os.getenv("S3_BUCKET_NAME") or "").strip() or None,
        region=(
            (os.getenv("S3_REGION") or "").strip()
            or (os.getenv("AWS_REGION") or "").strip()
            or DEFAULT_AWS_REGION
        ),
        endpoint_url=(os.getenv("S3_ENDPOINT_URL") or "").strip() or None,
    )


def max_upload_bytes() -> int:
    megabytes = _int("MAX_UPLOAD_SIZE_MB", DEFAULT_MAX_UPLOAD_SIZE_MB)
    if megabytes < 1:
        raise ValueError("MAX_UPLOAD_SIZE_MB must be at least 1")
    return megabytes * 1024 * 1024


def pending_upload_ttl_hours() -> int:
    hours = _int("PENDING_UPLOAD_TTL_HOURS", DEFAULT_PENDING_UPLOAD_TTL_HOURS)
    if hours < 1:
        raise ValueError("PENDING_UPLOAD_TTL_HOURS must be at least 1")
    return hours
