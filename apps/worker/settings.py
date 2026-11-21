import os
from dataclasses import dataclass
from typing import Final

DEFAULT_DEEPSEEK_API_URL: Final = "https://api.deepseek.com/chat/completions"
UPSTREAM_TIMEOUT_SECONDS: Final = 40.0
# the API computes the same default; DATABASE_URL overrides it
DEFAULT_DATABASE_URL: Final = "postgresql://rivet:rivet@localhost:5432/rivet"
# boto3 needs a region to build a client; AWS_REGION overrides it
DEFAULT_AWS_REGION: Final = "us-east-1"
# long polling is the SQS maximum; an idle worker stays quiet for 20s per call
DEFAULT_SQS_WAIT_TIME_SECONDS: Final = 20
# must exceed UPSTREAM_TIMEOUT_SECONDS, or SQS redelivers a job still in flight
DEFAULT_SQS_VISIBILITY_TIMEOUT: Final = 120
# one message at a time: a second one would sit visible while the first runs
DEFAULT_SQS_MAX_MESSAGES: Final = 1
# a claimed job is reclaimable just before SQS could redeliver it; the margin
# keeps a redelivery that lands on the boundary on the reclaiming side
RECLAIM_MARGIN_SECONDS: Final = 5
# one connection per process is enough for the single-threaded worker; RDS
# limits the total across instances, so both numbers are env-overridable
DEFAULT_POOL_MIN_SIZE: Final = 1
DEFAULT_POOL_MAX_SIZE: Final = 8
DEFAULT_MAX_UPLOAD_SIZE_MB: Final = 1
# a 1 MB document can hold far more text than is useful or affordable; this
# keeps one attachment from dominating the prompt
DEFAULT_MAX_ATTACHMENT_TEXT_CHARS: Final = 50_000


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str | None
    model: str


@dataclass(frozen=True)
class QueueSettings:
    """Where jobs arrive. A missing queue URL means the worker cannot start."""

    queue_url: str | None
    region: str
    endpoint_url: str | None
    wait_time_seconds: int
    visibility_timeout: int
    max_messages: int


@dataclass(frozen=True)
class StorageSettings:
    """Where attachments live. A missing bucket name only fails on first use."""

    bucket: str | None
    region: str
    endpoint_url: str | None


def _text(name: str) -> str | None:
    return (os.getenv(name) or "").strip() or None


def _int(name: str, default: int) -> int:
    raw = _text(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {raw!r}") from None


def load_deepseek_settings() -> DeepSeekSettings:
    api_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    return DeepSeekSettings(
        api_key=api_key or None,
        model=(os.getenv("DEEPSEEK_MODEL") or "").strip() or "deepseek-flash",
    )


def deepseek_api_url() -> str:
    return (os.getenv("DEEPSEEK_API_URL") or "").strip() or DEFAULT_DEEPSEEK_API_URL


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


def reclaim_seconds() -> int:
    """How long a claimed job stays owned before a redelivery may claim it again.

    SQS cannot hand the same message to a second worker before the visibility
    timeout expires, so a claim is refused for that long and no longer: a
    duplicate delivery inside the window is dropped, a redelivery after it wins.
    """
    return max(1, load_queue_settings().visibility_timeout - RECLAIM_MARGIN_SECONDS)


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip() or DEFAULT_DATABASE_URL


def max_attachment_bytes() -> int:
    megabytes = _int("MAX_UPLOAD_SIZE_MB", DEFAULT_MAX_UPLOAD_SIZE_MB)
    if megabytes < 1:
        raise ValueError("MAX_UPLOAD_SIZE_MB must be at least 1")
    return megabytes * 1024 * 1024


def max_attachment_text_chars() -> int:
    chars = _int("MAX_ATTACHMENT_TEXT_CHARS", DEFAULT_MAX_ATTACHMENT_TEXT_CHARS)
    if chars < 1:
        raise ValueError("MAX_ATTACHMENT_TEXT_CHARS must be at least 1")
    return chars


def load_queue_settings() -> QueueSettings:
    """Read the queue configuration on each call, so env changes need no restart."""
    return QueueSettings(
        queue_url=_text("SQS_QUEUE_URL"),
        region=_text("AWS_REGION") or DEFAULT_AWS_REGION,
        endpoint_url=_text("SQS_ENDPOINT_URL"),
        wait_time_seconds=_int("SQS_WAIT_TIME_SECONDS", DEFAULT_SQS_WAIT_TIME_SECONDS),
        visibility_timeout=_int(
            "SQS_VISIBILITY_TIMEOUT", DEFAULT_SQS_VISIBILITY_TIMEOUT
        ),
        max_messages=_int("SQS_MAX_MESSAGES", DEFAULT_SQS_MAX_MESSAGES),
    )


def load_storage_settings() -> StorageSettings:
    return StorageSettings(
        bucket=_text("S3_BUCKET_NAME"),
        region=_text("S3_REGION") or _text("AWS_REGION") or DEFAULT_AWS_REGION,
        endpoint_url=_text("S3_ENDPOINT_URL"),
    )
