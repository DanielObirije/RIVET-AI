from collections.abc import Callable

import pytest
from celery.exceptions import Retry

import tasks
from chat import ChatUpstreamError
from jobs import JobStore


def stub_completion(monkeypatch: pytest.MonkeyPatch, complete) -> list:
    calls: list = []

    def wrapper(messages, _settings):
        calls.append(messages)
        return complete()

    monkeypatch.setattr(tasks, "complete_chat", wrapper)
    monkeypatch.setattr(tasks, "load_deepseek_settings", lambda: None)
    return calls


def test_task_saves_the_reply(
    store: JobStore, queue_job: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = queue_job(store)
    stub_completion(monkeypatch, lambda: "Hello there")

    tasks.generate_reply(job_id)

    job = store.get(job_id)
    assert job is not None
    assert job.status == "succeeded"
    assert job.result == "Hello there"
    assert job.attempts == 1


def test_duplicate_delivery_does_not_run_twice(
    store: JobStore, queue_job: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = queue_job(store)
    calls = stub_completion(monkeypatch, lambda: "first reply")

    tasks.generate_reply(job_id)
    tasks.generate_reply(job_id)  # broker redelivered the same message

    job = store.get(job_id)
    assert job is not None
    assert job.result == "first reply"
    assert len(calls) == 1


def test_retryable_failure_requeues_the_job(
    store: JobStore, queue_job: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = queue_job(store)

    def fail():
        raise ChatUpstreamError("timeout", retryable=True)

    stub_completion(monkeypatch, fail)

    with pytest.raises(Retry):
        tasks.generate_reply(job_id)

    job = store.get(job_id)
    assert job is not None
    assert job.status == "queued"
    assert job.error_code is None


def test_permanent_failure_marks_the_job_failed(
    store: JobStore, queue_job: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = queue_job(store)

    def fail():
        raise ChatUpstreamError("rate_limit", retryable=False)

    stub_completion(monkeypatch, fail)

    tasks.generate_reply(job_id)

    job = store.get(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "rate_limit"


def test_unexpected_crash_marks_the_job_failed(
    store: JobStore, queue_job: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = queue_job(store)

    def fail():
        raise RuntimeError("boom")

    stub_completion(monkeypatch, fail)

    tasks.generate_reply(job_id)

    job = store.get(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.error_code == "server_error"
