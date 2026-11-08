from functools import lru_cache
from typing import Final

from celery import Celery

from app.config import broker_url

# the worker registers its task under this name; both sides are configured, not
# imported, so neither service needs the other's code
TASK_NAME: Final = "rivet.tasks.generate_reply"


@lru_cache(maxsize=1)
def celery_client() -> Celery:
    return Celery("rivet_api", broker=broker_url())


def enqueue_job(job_id: str) -> None:
    """Hand a job to the worker by task name, so no worker code is imported here."""
    celery_client().send_task(TASK_NAME, args=[job_id])
