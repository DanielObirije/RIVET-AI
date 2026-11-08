import logging
from typing import Final

from celery_app import celery
from chat import ChatUpstreamError, complete_chat
from jobs import JobStore
from settings import load_deepseek_settings

logger = logging.getLogger(__name__)

# the API dispatches by this name; both sides are configured, not imported
TASK_NAME: Final = "rivet.tasks.generate_reply"
MAX_RETRIES: Final = 3
RETRY_BACKOFF_SECONDS: Final = 5


@celery.task(bind=True, name=TASK_NAME, max_retries=MAX_RETRIES)
def generate_reply(self, job_id: str) -> None:
    """Run one queued chat completion and record the outcome in the jobs table."""
    store = JobStore()
    job = store.start(job_id)
    if job is None:
        logger.info("Job %s ignored: unknown or already finished", job_id)
        return

    try:
        result = complete_chat(job.messages, load_deepseek_settings())
    except ChatUpstreamError as exc:
        if exc.retryable and self.request.retries < MAX_RETRIES:
            store.requeue(job_id)
            countdown = RETRY_BACKOFF_SECONDS * (2 ** self.request.retries)
            logger.warning(
                "Job %s failed with %s, retrying in %ss",
                job_id,
                exc.code,
                countdown,
            )
            # no exc= here: the custom exception is not JSON serialisable state
            raise self.retry(countdown=countdown) from None
        store.fail(job_id, exc.code)
        logger.error("Job %s failed permanently: %s", job_id, exc.code)
        return
    except Exception:
        logger.exception("Job %s crashed", job_id)
        store.fail(job_id, "server_error")
        return

    store.succeed(job_id, result)
    logger.info("Job %s finished", job_id)
