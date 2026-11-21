"""Every SQS call the worker makes.

Named `sqs_queue` rather than `queue`: this folder is on `sys.path` when the
worker runs, so a module called `queue` would shadow the standard library one
that boto3 and psycopg import.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from settings import QueueSettings, load_queue_settings

# matches the body the API writes in apps/api/app/queue.py; kept in step by hand
JOB_ID_KEY = "job_id"


class QueueUnavailable(Exception):
    """An SQS call failed; the message state is unknown, so nothing is assumed."""


@dataclass(frozen=True)
class ReceivedMessage:
    message_id: str
    receipt_handle: str
    body: str


@lru_cache(maxsize=None)
def sqs_client(settings: QueueSettings) -> Any:
    """Build the client once per configuration; boto3 resolves credentials per call.

    Importing this module needs no AWS credentials, so the tests and a plain
    `python -c "import worker"` work on a machine with no AWS access.
    """
    return boto3.client(
        "sqs", region_name=settings.region, endpoint_url=settings.endpoint_url
    )


def _client(settings: QueueSettings, sqs: Any | None) -> Any:
    return sqs or sqs_client(settings)


def _url(settings: QueueSettings, queue_url: str | None) -> str:
    url = queue_url or settings.queue_url
    if not url:
        raise QueueUnavailable("SQS_QUEUE_URL is not configured")
    return url


def receive_messages(
    *,
    settings: QueueSettings | None = None,
    sqs: Any | None = None,
    queue_url: str | None = None,
    wait_time_seconds: int | None = None,
    max_messages: int | None = None,
) -> list[ReceivedMessage]:
    """Long-poll the queue for up to `max_messages` messages.

    A received message is invisible to other workers for `visibility_timeout`
    seconds. Anything that is not deleted in that window comes back.
    """
    settings = settings or load_queue_settings()
    url = _url(settings, queue_url)
    wait = settings.wait_time_seconds if wait_time_seconds is None else wait_time_seconds
    batch = settings.max_messages if max_messages is None else max_messages
    try:
        response = _client(settings, sqs).receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=batch,
            WaitTimeSeconds=wait,
            VisibilityTimeout=settings.visibility_timeout,
        )
    except (BotoCoreError, ClientError) as exc:
        raise QueueUnavailable(str(exc)) from exc

    return [
        ReceivedMessage(
            message_id=item.get("MessageId", ""),
            receipt_handle=item.get("ReceiptHandle", ""),
            body=item.get("Body", ""),
        )
        for item in response.get("Messages", [])
    ]


def delete_message(
    receipt_handle: str,
    *,
    settings: QueueSettings | None = None,
    sqs: Any | None = None,
    queue_url: str | None = None,
) -> None:
    """Acknowledge a message. Only call this once the job row is committed."""
    settings = settings or load_queue_settings()
    url = _url(settings, queue_url)
    try:
        _client(settings, sqs).delete_message(QueueUrl=url, ReceiptHandle=receipt_handle)
    except (BotoCoreError, ClientError) as exc:
        raise QueueUnavailable(str(exc)) from exc


def parse_job_id(body: str) -> str | None:
    """Read the job id out of a message body, or None if it is not one of ours."""
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    job_id = payload.get(JOB_ID_KEY)
    return job_id if isinstance(job_id, str) and job_id else None
