"""The long-running worker process: poll SQS, run one job, acknowledge it.

Run it from this folder:

    python worker.py   # poll SQS_QUEUE_URL until SIGTERM/SIGINT
"""

import logging
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv

from processor import Outcome, process_job
from settings import QueueSettings, load_queue_settings
from sqs_queue import (
    QueueUnavailable,
    ReceivedMessage,
    delete_message,
    parse_job_id,
    receive_messages,
)

logger = logging.getLogger(__name__)

# a failed receive (SQS unreachable) must not spin the loop at full speed
RECEIVE_ERROR_BACKOFF_SECONDS: Final = 5

# the file this loop touches and the image's HEALTHCHECK stats; keep the path
# and the age limit in worker's Dockerfile in step with this constant
DEFAULT_HEARTBEAT_PATH: Final = "/tmp/worker-heartbeat"


def handle_message(
    message: ReceivedMessage,
    *,
    settings: QueueSettings | None = None,
    sqs: Any | None = None,
    dsn: str | None = None,
) -> Outcome:
    """Run one message and acknowledge it only if the job row is committed."""
    job_id = parse_job_id(message.body)
    if job_id is None:
        # not one of our messages: no row to update and redelivery cannot fix it
        logger.error("Discarding message %s: no job id in the body", message.message_id)
        _acknowledge(message, settings=settings, sqs=sqs)
        return Outcome.DONE

    outcome = process_job(job_id, dsn=dsn)
    if outcome is Outcome.DONE:
        _acknowledge(message, settings=settings, sqs=sqs)
    else:
        logger.warning("Job %s left on the queue for redelivery", job_id)
    return outcome


def _acknowledge(
    message: ReceivedMessage,
    *,
    settings: QueueSettings | None,
    sqs: Any | None,
) -> None:
    """Delete a message; a failure here only means it will be redelivered."""
    try:
        delete_message(message.receipt_handle, settings=settings, sqs=sqs)
    except QueueUnavailable as exc:
        logger.error("Could not delete message %s: %s", message.message_id, exc)


def heartbeat_path() -> str:
    """Where the loop proves it is still turning; the image's HEALTHCHECK reads it."""
    return (os.getenv("WORKER_HEARTBEAT_PATH") or "").strip() or DEFAULT_HEARTBEAT_PATH


_heartbeat_unwritable = False


def record_heartbeat() -> None:
    """Touch the heartbeat file. A read-only path must not stop the worker."""
    global _heartbeat_unwritable
    path = heartbeat_path()
    try:
        Path(path).touch()
    except OSError as exc:
        if not _heartbeat_unwritable:
            logger.warning("Cannot write heartbeat %s: %s", path, exc)
            _heartbeat_unwritable = True


def run(
    stop: threading.Event,
    *,
    settings: QueueSettings | None = None,
    sqs: Any | None = None,
    dsn: str | None = None,
) -> None:
    """Poll until `stop` is set, handling messages one at a time."""
    settings = settings or load_queue_settings()
    if not settings.queue_url:
        raise QueueUnavailable("SQS_QUEUE_URL is not configured")

    logger.info("Polling %s", settings.queue_url)
    record_heartbeat()
    while not stop.is_set():
        try:
            messages = receive_messages(settings=settings, sqs=sqs)
        except QueueUnavailable as exc:
            logger.error("SQS receive failed: %s", exc)
            stop.wait(RECEIVE_ERROR_BACKOFF_SECONDS)
            record_heartbeat()
            continue

        # an idle long poll and a job in flight both count as alive
        record_heartbeat()
        for message in messages:
            handle_message(message, settings=settings, sqs=sqs, dsn=dsn)
            record_heartbeat()
            if stop.is_set():
                # the rest of the batch stays unacknowledged; SQS redelivers it
                break

    logger.info("Worker stopped")


def _install_signal_handlers(stop: threading.Event) -> None:
    def shut_down(signum: int, _frame: object) -> None:
        logger.info("Received signal %s, finishing the current job", signum)
        stop.set()

    signal.signal(signal.SIGTERM, shut_down)
    signal.signal(signal.SIGINT, shut_down)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    load_dotenv()

    try:
        stop = threading.Event()
        _install_signal_handlers(stop)
        run(stop)
    except QueueUnavailable as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
