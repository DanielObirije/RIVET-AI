import os
from collections.abc import Callable

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.jobs import JobStore, ensure_schema
from app.main import app

DEFAULT_TEST_DATABASE_URL = "postgresql://rivet:rivet@localhost:5432/rivet_test"

# the suite truncates this database, so it is never the development one
TEST_DATABASE_URL = os.getenv("RIVET_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the jobs table once per run; the DDL lives in app.jobs."""
    ensure_schema(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def empty_jobs_table(database: None) -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE TABLE jobs")


@pytest.fixture
def store() -> JobStore:
    return JobStore()


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr("app.jobs.enqueue_job", sent.append)
    return sent


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def advance() -> Callable[..., None]:
    """Stands in for the worker, the only process that moves a job onward."""

    def advance_job(
        store: JobStore, job_id: str, status: str, result: str | None = None
    ) -> None:
        with psycopg.connect(store.dsn) as conn:
            conn.execute(
                "UPDATE jobs SET status = %s, result = %s WHERE id = %s",
                (status, result, job_id),
            )

    return advance_job
