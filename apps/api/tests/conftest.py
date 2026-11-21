import os
from collections.abc import Callable

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.jobs import ensure_schema
from app.main import app
from fakes import FakeS3

DEFAULT_TEST_DATABASE_URL = "postgresql://rivet:rivet@localhost:5432/rivet_test"

# the suite truncates this database, so it is never the development one
TEST_DATABASE_URL = os.getenv("RIVET_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the tables once per run; the DDL lives in app.jobs."""
    ensure_schema(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def empty_jobs_table(database: None) -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE TABLE jobs, attachments")


@pytest.fixture(autouse=True)
def storage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bucket name and no real endpoint; no test may build a real S3 client."""
    monkeypatch.setenv("S3_BUCKET_NAME", "rivet-assets")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "1")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)


@pytest.fixture
def fake_s3(monkeypatch: pytest.MonkeyPatch) -> FakeS3:
    fake = FakeS3()
    monkeypatch.setattr("app.storage.s3_client", lambda settings: fake)
    return fake


@pytest.fixture
def dsn() -> str:
    """The connection string the job functions default to via DATABASE_URL."""
    return TEST_DATABASE_URL


@pytest.fixture(autouse=True)
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captures published job ids; no test may build a real SQS client."""
    sent: list[str] = []
    monkeypatch.setattr("app.jobs.publish_job", sent.append)
    return sent


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def advance(dsn: str) -> Callable[..., None]:
    """Stands in for the worker, the only process that moves a job onward."""

    def advance_job(job_id: str, status: str, result: str | None = None) -> None:
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "UPDATE jobs SET status = %s, result = %s WHERE id = %s",
                (status, result, job_id),
            )

    return advance_job
