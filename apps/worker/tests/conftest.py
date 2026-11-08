import json
import os
from collections.abc import Callable

import psycopg
import pytest

from jobs import JobStore, ensure_schema

DEFAULT_TEST_DATABASE_URL = "postgresql://rivet:rivet@localhost:5432/rivet_test"

# the suite truncates this database, so it is never the development one
TEST_DATABASE_URL = os.getenv("RIVET_TEST_DATABASE_URL") or DEFAULT_TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the jobs table once per run; the DDL lives in jobs.py."""
    ensure_schema(TEST_DATABASE_URL)


@pytest.fixture(autouse=True)
def empty_jobs_table(database: None) -> None:
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE TABLE jobs")


@pytest.fixture
def store() -> JobStore:
    return JobStore()


@pytest.fixture
def queue_job() -> Callable[..., str]:
    """Stands in for the API, the only process that creates a job row."""

    def queue(store: JobStore, job_id: str = "job-1") -> str:
        with psycopg.connect(store.dsn) as conn:
            conn.execute(
                "INSERT INTO jobs (id, status, messages, created_at, updated_at)"
                " VALUES (%s, 'queued', %s, now(), now())",
                (job_id, json.dumps([{"role": "user", "content": "Hi"}])),
            )
        return job_id

    return queue
