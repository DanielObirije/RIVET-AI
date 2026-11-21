import json
import signal
import threading
from collections.abc import Callable
from dataclasses import replace

import pytest
from botocore.exceptions import ClientError
from fakes import FakeSqs, message

import worker
from chat import ChatUpstreamError
from jobs import get_job, start_job
from processor import Outcome
from sqs_queue import QueueUnavailable, ReceivedMessage
from worker import handle_message, run


def deliver(job_id: str) -> ReceivedMessage:
    """The object the queue module hands back for one delivered message."""
    return ReceivedMessage(
        message_id=f"msg-{job_id}",
        receipt_handle=f"rh-{job_id}",
        body=json.dumps({"job_id": job_id}),
    )


def test_a_saved_job_is_acknowledged(
    dsn: str,
    queue_job: Callable[..., str],
    queue_settings,
    fake_sqs: FakeSqs,
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()
    stub_completion(lambda: "Hello there")
    # what the row said at the moment SQS was asked to delete the message
    status_at_delete: list[str | None] = []

    def on_delete(_handle: str) -> None:
        row = get_job(job_id, dsn=dsn)
        status_at_delete.append(row.status if row is not None else None)

    fake_sqs.on_delete = on_delete

    outcome = handle_message(
        deliver(job_id), settings=queue_settings, sqs=fake_sqs, dsn=dsn
    )

    assert outcome is Outcome.DONE
    assert fake_sqs.deleted == [f"rh-{job_id}"]
    assert status_at_delete == ["succeeded"]


def test_a_retryable_failure_leaves_the_message(
    dsn: str,
    queue_job: Callable[..., str],
    queue_settings,
    fake_sqs: FakeSqs,
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()

    def fail():
        raise ChatUpstreamError("network", retryable=True)

    stub_completion(fail)

    outcome = handle_message(
        deliver(job_id), settings=queue_settings, sqs=fake_sqs, dsn=dsn
    )

    assert outcome is Outcome.RETRY
    assert fake_sqs.deleted == []


def test_a_duplicate_delivery_of_a_running_job_is_acknowledged(
    dsn: str,
    queue_job: Callable[..., str],
    queue_settings,
    fake_sqs: FakeSqs,
    stub_completion: Callable[..., list],
) -> None:
    """A second worker must not call the model for a job its peer already owns."""
    job_id = queue_job()
    assert start_job(job_id, dsn=dsn) is not None
    calls = stub_completion(lambda: "never used")

    outcome = handle_message(
        deliver(job_id), settings=queue_settings, sqs=fake_sqs, dsn=dsn
    )

    assert outcome is Outcome.DONE
    assert calls == []
    assert fake_sqs.deleted == [f"rh-{job_id}"]
    row = get_job(job_id, dsn=dsn)
    assert row is not None
    assert row.status == "running"
    assert row.attempts == 1


def test_a_message_without_a_job_id_is_discarded(
    queue_settings, fake_sqs: FakeSqs
) -> None:
    junk = ReceivedMessage(message_id="msg-junk", receipt_handle="rh-junk", body="hi")

    outcome = handle_message(junk, settings=queue_settings, sqs=fake_sqs)

    assert outcome is Outcome.DONE
    assert fake_sqs.deleted == ["rh-junk"]


def test_a_failed_delete_is_not_fatal(
    dsn: str,
    queue_job: Callable[..., str],
    queue_settings,
    fake_sqs: FakeSqs,
    stub_completion: Callable[..., list],
) -> None:
    """Deleting is the last step; if it fails the job is simply redelivered."""
    job_id = queue_job()
    stub_completion(lambda: "Hello there")
    fake_sqs.error = ClientError(
        {"Error": {"Code": "InternalError", "Message": "try again"}}, "DeleteMessage"
    )

    outcome = handle_message(
        deliver(job_id), settings=queue_settings, sqs=fake_sqs, dsn=dsn
    )

    assert outcome is Outcome.DONE
    row = get_job(job_id, dsn=dsn)
    assert row is not None
    assert row.status == "succeeded"


def test_run_handles_a_batch_then_stops(
    dsn: str,
    queue_job: Callable[..., str],
    queue_settings,
    fake_sqs: FakeSqs,
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()
    stub_completion(lambda: "Hello there")
    fake_sqs.inbox = [message(job_id)]
    stop = threading.Event()
    # one long poll is enough; the signal handler would do this in production
    fake_sqs.on_receive = stop.set

    run(stop, settings=queue_settings, sqs=fake_sqs, dsn=dsn)

    assert len(fake_sqs.receive_calls) == 1
    assert fake_sqs.deleted == [f"rh-{job_id}"]
    row = get_job(job_id, dsn=dsn)
    assert row is not None
    assert row.status == "succeeded"


def test_run_keeps_polling_after_a_receive_error(
    queue_settings, fake_sqs: FakeSqs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "RECEIVE_ERROR_BACKOFF_SECONDS", 0)
    stop = threading.Event()
    attempts: list[dict] = []

    def flaky(**kwargs) -> list:
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise QueueUnavailable("SQS is unreachable")
        stop.set()
        return []

    monkeypatch.setattr(worker, "receive_messages", flaky)

    run(stop, settings=queue_settings, sqs=fake_sqs)

    assert len(attempts) == 2


def test_run_needs_a_queue_url(queue_settings, fake_sqs: FakeSqs) -> None:
    with pytest.raises(QueueUnavailable):
        run(
            threading.Event(),
            settings=replace(queue_settings, queue_url=None),
            sqs=fake_sqs,
        )


def test_signal_handlers_stop_the_loop() -> None:
    stop = threading.Event()
    previous = {
        sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        worker._install_signal_handlers(stop)

        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)  # type: ignore[operator]

        assert stop.is_set()
    finally:
        for sig, restore in previous.items():
            signal.signal(sig, restore)


def test_main_reports_a_queue_it_cannot_use(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args, **_kwargs) -> None:
        raise QueueUnavailable("SQS_QUEUE_URL is not configured")

    monkeypatch.setattr(worker, "run", explode)

    assert worker.main() == 1
