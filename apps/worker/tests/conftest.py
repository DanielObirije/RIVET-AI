import json
import os
from collections.abc import Callable

import psycopg
import pytest

import processor
from fakes import FakeS3, FakeSqs
from jobs import ensure_schema
from settings import QueueSettings, StorageSettings

DEFAULT_TEST_DATABASE_URL = "postgresql://rivet:rivet@localhost:5432/rivet_test"

# the suite truncates this database, so it is never the development one
TEST_DATABASE_URL = os.getenv("RIVET_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/rivet-jobs"


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the jobs table once per run; the DDL lives in jobs.py."""
    ensure_schema(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def empty_jobs_table(database: None) -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE TABLE jobs")


@pytest.fixture
def dsn() -> str:
    """The connection string every job function is handed explicitly."""
    return TEST_DATABASE_URL


@pytest.fixture
def queue_settings() -> QueueSettings:
    return QueueSettings(
        queue_url=QUEUE_URL,
        region="us-east-1",
        endpoint_url=None,
        # zero, so a real client would never block if one ever got built
        wait_time_seconds=0,
        visibility_timeout=120,
        max_messages=1,
    )


@pytest.fixture
def storage_settings() -> StorageSettings:
    return StorageSettings(
        bucket="rivet-assets", region="us-east-1", endpoint_url=None
    )


@pytest.fixture
def fake_sqs() -> FakeSqs:
    return FakeSqs()


@pytest.fixture
def fake_s3() -> FakeS3:
    return FakeS3()


@pytest.fixture
def stub_completion(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable], list]:
    """Replace the DeepSeek call; returns the conversations it was handed."""

    def install(complete: Callable[[], str]) -> list:
        calls: list = []

        def wrapper(messages, _settings):
            calls.append(messages)
            return complete()

        monkeypatch.setattr(processor, "complete_chat", wrapper)
        monkeypatch.setattr(processor, "load_deepseek_settings", lambda: None)
        return calls

    return install


@pytest.fixture
def queue_job(dsn: str) -> Callable[..., str]:
    """Stands in for the API, the only process that creates a job row."""

    def queue(job_id: str = "job-1") -> str:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO jobs (id, status, messages, created_at, updated_at)"
                " VALUES (%s, 'queued', %s, now(), now())",
                (job_id, json.dumps([{"role": "user", "content": "Hi"}])),
            )
        return job_id

    return queue
