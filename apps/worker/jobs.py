import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from psycopg import Connection, errors
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from settings import database_url, pool_sizes, reclaim_seconds

QUEUED: Final = "queued"
RUNNING: Final = "running"
SUCCEEDED: Final = "succeeded"
FAILED: Final = "failed"

# same DDL as apps/api/app/jobs.py; the two services share one table and neither
# runs a migration tool, so keep the two copies in step by hand
JOBS_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    messages    TEXT NOT NULL,
    result      TEXT,
    error_code  TEXT,
    retry_of    TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
)
"""

# a table created before retry_of existed; there is no migration tool, so the
# column is added in place, idempotently, on first use
ADD_RETRY_OF: Final = "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retry_of TEXT"

# one pool per process and connection string, opened on first use so the worker
# can start before the database is reachable
_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def _pool(dsn: str) -> ConnectionPool:
    with _pools_lock:
        pool = _pools.get(dsn)
        if pool is None:
            min_size, max_size = pool_sizes()
            pool = ConnectionPool(
                dsn,
                min_size=min_size,
                max_size=max_size,
                kwargs={"row_factory": dict_row},
                # a task fails fast instead of hanging when the database is down
                timeout=5.0,
                open=False,
            )
            pool.open()
            _pools[dsn] = pool
    return pool


_schema_lock = threading.Lock()
_schema_ready: set[str] = set()


def ensure_schema(dsn: str | None = None) -> None:
    """Create the `jobs` table if it is missing, once per process and URL."""
    dsn = dsn or database_url()
    with _schema_lock:
        if dsn in _schema_ready:
            return
        with _pool(dsn).connection() as conn:
            try:
                conn.execute(JOBS_SCHEMA)
            except (errors.DuplicateTable, errors.UniqueViolation):
                # the API created the table between our check and this DDL
                conn.rollback()
            conn.execute(ADD_RETRY_OF)
        _schema_ready.add(dsn)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Job:
    id: str
    status: str
    messages: list[tuple[str, str]]
    result: str | None
    error_code: str | None
    attempts: int


def job_from_row(row: DictRow) -> Job:
    stored = json.loads(row["messages"])
    return Job(
        id=row["id"],
        status=row["status"],
        messages=[(item["role"], item["content"]) for item in stored],
        result=row["result"],
        error_code=row["error_code"],
        attempts=row["attempts"],
    )


@contextmanager
def _transaction(dsn: str | None) -> Iterator[Connection[DictRow]]:
    """Check out one pooled connection and commit one transaction per call.

    Every caller passes its own `dsn`, so concurrent tasks never share a handle
    and a test can point at its own database.
    """
    resolved = dsn or database_url()
    ensure_schema(resolved)
    with _pool(resolved).connection() as conn:
        yield conn
        conn.commit()


def get_job(job_id: str, *, dsn: str | None = None) -> Job | None:
    with _transaction(dsn) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
    return job_from_row(row) if row is not None else None


def start_job(
    job_id: str, *, dsn: str | None = None, owned_for: int | None = None
) -> Job | None:
    """Claim a pending job; returns None when it is unknown, done or still owned.

    The claim is one conditional UPDATE ... RETURNING, so the row lock makes it
    atomic across concurrent workers: of two workers handed the same message,
    the second sees `running` and gets no row back.

    A `running` row is reclaimed only after `owned_for` seconds, which is when
    SQS can redeliver a message whose worker died mid-task. A duplicate delivery
    inside that window is refused instead of run twice.
    """
    owner_window = reclaim_seconds() if owned_for is None else owned_for
    with _transaction(dsn) as conn:
        row = conn.execute(
            # both sides of the comparison use the database clock, so two
            # instances with skewed clocks cannot disagree about the lease
            "UPDATE jobs SET status = %s, attempts = attempts + 1, updated_at = now()"
            " WHERE id = %s"
            " AND (status = %s OR (status = %s"
            " AND updated_at <= now() - make_interval(secs => %s)))"
            " RETURNING *",
            (RUNNING, job_id, QUEUED, RUNNING, owner_window),
        ).fetchone()
    return job_from_row(row) if row is not None else None


def requeue_job(job_id: str, *, dsn: str | None = None) -> None:
    _set_outcome(job_id, status=QUEUED, dsn=dsn)


def succeed_job(job_id: str, result: str, *, dsn: str | None = None) -> None:
    _set_outcome(job_id, status=SUCCEEDED, result=result, dsn=dsn)


def fail_job(job_id: str, error_code: str, *, dsn: str | None = None) -> None:
    _set_outcome(job_id, status=FAILED, error_code=error_code, dsn=dsn)


def _set_outcome(
    job_id: str,
    *,
    status: str,
    result: str | None = None,
    error_code: str | None = None,
    dsn: str | None = None,
) -> None:
    with _transaction(dsn) as conn:
        conn.execute(
            "UPDATE jobs SET status = %s, result = %s, error_code = %s,"
            " updated_at = %s WHERE id = %s",
            (status, result, error_code, _now(), job_id),
        )
