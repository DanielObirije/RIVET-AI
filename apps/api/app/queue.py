import json
import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config import SqsSettings, load_sqs_settings

logger = logging.getLogger(__name__)


class QueueUnavailable(Exception):
    """The job id never reached the queue, so no worker will ever see the job."""


@lru_cache(maxsize=None)
def sqs_client(settings: SqsSettings) -> Any:
    """Build the client once per configuration; boto3 resolves credentials per request.

    Nothing here needs AWS credentials at import time, so the module (and the
    test suite) loads on a machine with no AWS access at all.
    """
    return boto3.client(
        "sqs", region_name=settings.region, endpoint_url=settings.endpoint_url
    )


def publish_job(
    job_id: str,
    *,
    settings: SqsSettings | None = None,
    sqs: Any | None = None,
) -> None:
    """Publish one job id to the queue.

    The message carries the id and nothing else: the conversation and the result
    live in PostgreSQL, so a redelivered message always reads current state.
    Raises QueueUnavailable when no queue is configured or SQS rejects the send.
    """
    settings = settings or load_sqs_settings()
    if not settings.queue_url:
        raise QueueUnavailable("SQS_QUEUE_URL is not configured")

    client = sqs or sqs_client(settings)
    try:
        # apps/worker/sqs_queue.py parses this body; keep the two sides in step
        client.send_message(
            QueueUrl=settings.queue_url,
            MessageBody=json.dumps({"job_id": job_id}),
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("SQS send failed for job %s: %s", job_id, exc)
        raise QueueUnavailable(str(exc)) from exc
