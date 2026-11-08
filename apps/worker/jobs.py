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

from settings import database_url

QUEUED: Final = "queued"
RUNNING: Final = "running"
SUCCEEDED: Final = "succeeded"
FAILED: Final = "failed"
POOL_MIN_SIZE: Final = 1
POOL_MAX_SIZE: Final = 8

# same DDL as apps/api/app/jobs.py; the two services share one table and neither
# runs a migration tool, so keep the two copies in step by hand
JOBS_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    messages    TEXT NOT NULL,
    result      TEXT,
    error_code  TEXT,
    attempts    INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
)
"""

# one pool per process and connection string, opened on first use so the worker
# can start before the database is reachable
_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def _pool(dsn: str) -> ConnectionPool:
    with _pools_lock:
        pool = _pools.get(dsn)
        if pool is None:
            pool = ConnectionPool(
                dsn,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
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


def _to_job(row: DictRow) -> Job:
    stored = json.loads(row["messages"])
    return Job(
        id=row["id"],
        status=row["status"],
        messages=[(item["role"], item["content"]) for item in stored],
        result=row["result"],
        error_code=row["error_code"],
        attempts=row["attempts"],
    )


class JobStore:
    """The worker's side of the jobs table.

    A connection is checked out of the process-wide pool per call and its
    transaction is committed before the connection is returned, so this process
    never shares a handle with the API or with another task thread.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or database_url()

    @contextmanager
    def _db(self) -> Iterator[Connection[DictRow]]:
        ensure_schema(self.dsn)
        with _pool(self.dsn).connection() as conn:
            yield conn
            conn.commit()

    def get(self, job_id: str) -> Job | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = %s", (job_id,)
            ).fetchone()
        return _to_job(row) if row is not None else None

    def start(self, job_id: str) -> Job | None:
        """Claim a pending job; returns None when it is unknown or already done.

        The claim is one conditional UPDATE ... RETURNING, so the row lock makes
        it atomic across concurrent workers. A redelivered message for a job
        still marked running is reclaimed, so a worker that died mid-task does
        not strand the job forever.
        """
        with self._db() as conn:
            row = conn.execute(
                "UPDATE jobs SET status = %s, attempts = attempts + 1, updated_at = %s"
                " WHERE id = %s AND status IN (%s, %s)"
                " RETURNING *",
                (RUNNING, _now(), job_id, QUEUED, RUNNING),
            ).fetchone()
        return _to_job(row) if row is not None else None

    def requeue(self, job_id: str) -> None:
        self._set(job_id, status=QUEUED)

    def succeed(self, job_id: str, result: str) -> None:
        self._set(job_id, status=SUCCEEDED, result=result)

    def fail(self, job_id: str, error_code: str) -> None:
        self._set(job_id, status=FAILED, error_code=error_code)

    def _set(
        self,
        job_id: str,
        *,
        status: str,
        result: str | None = None,
        error_code: str | None = None,
    ) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE jobs SET status = %s, result = %s, error_code = %s,"
                " updated_at = %s WHERE id = %s",
                (status, result, error_code, _now(), job_id),
            )
