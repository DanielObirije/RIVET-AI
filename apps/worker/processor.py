"""The job execution lifecycle: claim, run, persist, and say what to do next."""

import logging
from enum import Enum
from typing import Final

from chat import ChatUpstreamError, complete_chat
from jobs import (
    fail_job,
    get_job,
    requeue_job,
    start_job,
    succeed_job,
)
from settings import DeepSeekSettings, load_deepseek_settings

logger = logging.getLogger(__name__)

SERVER_ERROR: Final = "server_error"


class Outcome(Enum):
    """What the worker should do with the message it has just handled."""

    DONE = "done"  # the row is committed, so the message can be deleted
    RETRY = "retry"  # nothing was committed, so leave the message for redelivery


def process_job(
    job_id: str,
    *,
    dsn: str | None = None,
    settings: DeepSeekSettings | None = None,
) -> Outcome:
    """Run one job and record its outcome.

    DONE means the database already holds the final state, whether that is
    success or a permanent failure. RETRY means it does not: the claim was
    refused by the database, a retryable upstream error happened, or a write
    failed. Either way the caller must not delete the message for RETRY.
    """
    try:
        job = start_job(job_id, dsn=dsn)
    except Exception:
        logger.exception("Job %s: could not claim it, leaving it on the queue", job_id)
        return Outcome.RETRY

    if job is None:
        return _ignore(job_id, dsn=dsn)

    try:
        result = complete_chat(job.messages, settings or load_deepseek_settings())
    except ChatUpstreamError as exc:
        return _record_failure(job_id, exc.code, retryable=exc.retryable, dsn=dsn)
    except Exception:
        logger.exception("Job %s crashed", job_id)
        return _record_failure(job_id, SERVER_ERROR, retryable=False, dsn=dsn)

    try:
        succeed_job(job_id, result, dsn=dsn)
    except Exception:
        # the model answered but the row does not say so: redelivery reruns it
        logger.exception("Job %s: could not save the reply", job_id)
        return Outcome.RETRY

    logger.info("Job %s finished", job_id)
    return Outcome.DONE


def _ignore(job_id: str, *, dsn: str | None) -> Outcome:
    """The claim returned no row: the job is unknown or already finished."""
    try:
        existing = get_job(job_id, dsn=dsn)
    except Exception:
        logger.exception("Job %s: could not read its row", job_id)
        return Outcome.RETRY

    if existing is None:
        # no row at all: redelivering cannot help, and there is nothing to record
        logger.error("Job %s ignored: no such job", job_id)
        return Outcome.DONE

    logger.info("Job %s ignored: already %s", job_id, existing.status)
    return Outcome.DONE


def _record_failure(
    job_id: str, code: str, *, retryable: bool, dsn: str | None
) -> Outcome:
    try:
        if retryable:
            requeue_job(job_id, dsn=dsn)
        else:
            fail_job(job_id, code, dsn=dsn)
    except Exception:
        logger.exception("Job %s: could not record %s", job_id, code)
        return Outcome.RETRY

    if retryable:
        logger.warning("Job %s: %s, leaving it for redelivery", job_id, code)
        return Outcome.RETRY

    logger.error("Job %s failed permanently: %s", job_id, code)
    return Outcome.DONE
