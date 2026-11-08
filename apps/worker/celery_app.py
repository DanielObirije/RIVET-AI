import logging

from celery import Celery
from dotenv import load_dotenv

from settings import broker_url

load_dotenv()

logger = logging.getLogger(__name__)

celery = Celery("rivet_worker", broker=broker_url(), include=["tasks"])

celery.conf.update(
    # job state lives in the jobs table, so Celery does not keep results
    task_ignore_result=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # a redelivered job is reclaimed instead of being lost when a worker dies
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)
