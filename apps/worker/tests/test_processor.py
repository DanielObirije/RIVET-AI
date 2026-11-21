from collections.abc import Callable

import psycopg
import pytest

import processor
from chat import ChatUpstreamError
from jobs import get_job, succeed_job
from processor import Outcome, process_job


class WorkerDied(BaseException):
    """Stands in for the process dying mid-job: no write, no acknowledgement."""


def test_success_saves_the_reply(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()
    stub_completion(lambda: "Hello there")

    outcome = process_job(job_id, dsn=dsn)

    assert outcome is Outcome.DONE
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "succeeded"
    assert job.result == "Hello there"
    assert job.attempts == 1


def test_duplicate_delivery_does_not_run_twice(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()
    calls = stub_completion(lambda: "first reply")

    process_job(job_id, dsn=dsn)
    second = process_job(job_id, dsn=dsn)  # SQS redelivered the same message

    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.result == "first reply"
    assert len(calls) == 1
    assert second is Outcome.DONE


def test_an_unknown_job_is_ignored(
    dsn: str, stub_completion: Callable[..., list]
) -> None:
    calls = stub_completion(lambda: "never")

    outcome = process_job("does-not-exist", dsn=dsn)

    assert outcome is Outcome.DONE
    assert calls == []


def test_a_finished_job_is_ignored(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()
    succeed_job(job_id, "already done", dsn=dsn)
    calls = stub_completion(lambda: "never")

    outcome = process_job(job_id, dsn=dsn)

    assert outcome is Outcome.DONE
    assert calls == []
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.result == "already done"


def test_retryable_failure_requeues_and_asks_for_redelivery(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()

    def fail():
        raise ChatUpstreamError("timeout", retryable=True)

    stub_completion(fail)

    outcome = process_job(job_id, dsn=dsn)

    assert outcome is Outcome.RETRY
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "queued"
    assert job.error_code is None


def test_permanent_failure_is_recorded_then_acknowledged(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()

    def fail():
        raise ChatUpstreamError("rate_limit", retryable=False)

    stub_completion(fail)

    outcome = process_job(job_id, dsn=dsn)

    assert outcome is Outcome.DONE
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "rate_limit"


def test_unexpected_exception_is_recorded_as_a_server_error(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    job_id = queue_job()

    def fail():
        raise RuntimeError("boom")

    stub_completion(fail)

    outcome = process_job(job_id, dsn=dsn)

    assert outcome is Outcome.DONE
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "server_error"


def test_a_failed_write_leaves_the_job_for_redelivery(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reply was not persisted, so the message must not be acknowledged."""
    job_id = queue_job()
    stub_completion(lambda: "Hello there")

    def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(processor, "succeed_job", boom)

    outcome = process_job(job_id, dsn=dsn)

    assert outcome is Outcome.RETRY
    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "running"
    assert job.result is None


def test_a_failed_claim_leaves_the_job_for_redelivery(
    dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(processor, "start_job", boom)

    assert process_job("job-1", dsn=dsn) is Outcome.RETRY


def test_a_failed_status_read_leaves_the_job_for_redelivery(
    dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The claim found no row, but the status read failed: try again later."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(processor, "get_job", boom)

    assert process_job("does-not-exist", dsn=dsn) is Outcome.RETRY


def test_a_failed_failure_write_leaves_the_job_for_redelivery(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = queue_job()

    def fail():
        raise ChatUpstreamError("rate_limit", retryable=False)

    stub_completion(fail)

    def boom(*_args, **_kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(processor, "fail_job", boom)

    assert process_job(job_id, dsn=dsn) is Outcome.RETRY


def test_a_crash_mid_job_is_reclaimed_on_redelivery(
    dsn: str,
    queue_job: Callable[..., str],
    stub_completion: Callable[..., list],
) -> None:
    """A worker that dies after claiming leaves `running`, not a lost job."""
    job_id = queue_job()

    def die():
        raise WorkerDied()

    stub_completion(die)
    with pytest.raises(WorkerDied):
        process_job(job_id, dsn=dsn)

    crashed = get_job(job_id, dsn=dsn)
    assert crashed is not None
    assert crashed.status == "running"

    # SQS redelivers only after the visibility timeout, so the claim is stale
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE jobs SET updated_at = now() - interval '10 minutes' WHERE id = %s",
            (job_id,),
        )

    stub_completion(lambda: "second time lucky")
    assert process_job(job_id, dsn=dsn) is Outcome.DONE

    job = get_job(job_id, dsn=dsn)
    assert job is not None
    assert job.status == "succeeded"
    assert job.result == "second time lucky"
    assert job.attempts == 2
