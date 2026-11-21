"""The job execution lifecycle: claim, run, persist, and say what to do next."""

import logging
from enum import Enum
from typing import Any, Final

from chat import ChatUpstreamError, complete_chat, model_supports_images
from documents import (
    AttachmentError,
    JPEG_MIME,
    PreparedAttachment,
    process_attachment,
)
from jobs import (
    ATTACHED,
    Attachment,
    fail_job,
    get_attachment,
    get_job,
    requeue_job,
    save_extracted_text,
    start_job,
    succeed_job,
)
from settings import (
    DeepSeekSettings,
    load_deepseek_settings,
    max_attachment_bytes,
    max_attachment_text_chars,
)
from storage import ObjectTooLarge, StorageUnavailable, read_object

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
    client: Any | None = None,
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

    deepseek = settings or load_deepseek_settings()
    try:
        prepared = (
            prepare_attachment(
                job.attachment_id, dsn=dsn, model=deepseek.model, client=client
            )
            if job.attachment_id
            else None
        )
    except ChatUpstreamError as exc:
        return _record_failure(job_id, exc.code, retryable=exc.retryable, dsn=dsn)

    messages = _with_attachment(job.messages, prepared)
    try:
        result = complete_chat(
            messages,
            deepseek,
            image_data_url=prepared.image_data_url if prepared else None,
        )
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


def prepare_attachment(
    attachment_id: str,
    *,
    dsn: str | None,
    model: str,
    client: Any | None = None,
) -> PreparedAttachment:
    """Turn the stored file into model input, or fail with a user-facing code."""
    attachment = get_attachment(attachment_id, dsn=dsn)
    if attachment is None or attachment.status != ATTACHED:
        raise ChatUpstreamError("attachment_missing", retryable=False)

    if attachment.extracted_text:
        return PreparedAttachment(
            filename=attachment.filename, text=attachment.extracted_text
        )

    if attachment.content_type == JPEG_MIME and not model_supports_images(model):
        # never send an image the model cannot see, and never pretend it can
        logger.error(
            "Attachment %s is an image but model %s has no image input",
            attachment.id,
            model,
        )
        raise ChatUpstreamError("image_unsupported", retryable=False)

    data = _download(attachment, client=client)
    try:
        prepared = process_attachment(attachment, data)
    except AttachmentError as exc:
        logger.error(
            "Attachment %s could not be read: %s", attachment.id, exc
        )
        raise ChatUpstreamError("attachment_unreadable", retryable=False) from None

    if prepared.text is None:
        return prepared

    text = _truncate(prepared.text, max_attachment_text_chars())
    try:
        save_extracted_text(attachment.id, text, dsn=dsn)
    except Exception:
        # the text is already in hand; a lost cache only costs one re-parse
        logger.warning("Could not cache extracted text for %s", attachment.id)

    return PreparedAttachment(filename=prepared.filename, text=text)


def _download(attachment: Attachment, *, client: Any | None) -> bytes:
    try:
        return read_object(
            attachment.s3_key,
            max_bytes=max_attachment_bytes(),
            client=client,
        )
    except ObjectTooLarge as exc:
        # a redelivery cannot make the object smaller
        logger.error("Attachment %s is too large: %s", attachment.id, exc)
        raise ChatUpstreamError("attachment_unreadable", retryable=False) from None
    except StorageUnavailable as exc:
        logger.error("Could not read attachment %s: %s", attachment.id, exc)
        raise ChatUpstreamError("storage_unavailable", retryable=True) from None


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[attachment text truncated]"


def _with_attachment(
    messages: list[tuple[str, str]], prepared: PreparedAttachment | None
) -> list[tuple[str, str]]:
    if prepared is None:
        return messages

    note = f'The user attached the file "{prepared.filename}".'
    if prepared.text:
        note = f"{note}\n\nIts extracted text follows:\n\n{prepared.text}"
    elif prepared.image_data_url:
        note = f"{note} The image is included with this message."

    updated = list(messages)
    for index in range(len(updated) - 1, -1, -1):
        role, content = updated[index]
        if role == "user":
            updated[index] = (role, f"{content}\n\n{note}")
            return updated

    updated.append(("user", note))
    return updated


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
