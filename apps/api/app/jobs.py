import json
import logging
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from psycopg import Connection, errors
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.celery_client import enqueue_job
from app.config import database_url
from app.errors import FRIENDLY_ERRORS, ChatError
from app.schemas import ALLOWED_ROLES, ChatMessage, JobResponse

logger = logging.getLogger(__name__)

QUEUED: Final = "queued"
FAILED: Final = "failed"
POOL_MIN_SIZE: Final = 1
POOL_MAX_SIZE: Final = 8

# same DDL as apps/worker/jobs.py; the two services share one table and neither
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

# one pool per process and connection string, opened on first use so importing
# the app never needs the database to be reachable
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
                # a request fails fast instead of hanging when the database is down
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
                # the worker created the table between our check and this DDL
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


def _to_job(row: DictRow) -> Job:
    stored = json.loads(row["messages"])
    return Job(
        id=row["id"],
        status=row["status"],
        messages=[(item["role"], item["content"]) for item in stored],
        result=row["result"],
        error_code=row["error_code"],
    )


class JobStore:
    """The API's side of the jobs table: it creates rows and reads them back.

    Only the worker advances a job past `queued`, so this store cannot mark one
    running or succeeded. Every call checks out a pooled connection and commits
    its own transaction, so concurrent requests never share a handle.
    """

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or database_url()

    @contextmanager
    def _db(self) -> Iterator[Connection[DictRow]]:
        ensure_schema(self.dsn)
        with _pool(self.dsn).connection() as conn:
            yield conn
            conn.commit()

    def create(self, messages: list[tuple[str, str]]) -> Job:
        job_id = uuid.uuid4().hex
        now = _now()
        payload = json.dumps(
            [{"role": role, "content": content} for role, content in messages]
        )
        with self._db() as conn:
            conn.execute(
                "INSERT INTO jobs (id, status, messages, created_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (job_id, QUEUED, payload, now, now),
            )
        return Job(job_id, QUEUED, list(messages), None, None)

    def get(self, job_id: str) -> Job | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = %s", (job_id,)
            ).fetchone()
        return _to_job(row) if row is not None else None

    def fail(self, job_id: str, error_code: str) -> None:
        with self._db() as conn:
            conn.execute(
                "UPDATE jobs SET status = %s, error_code = %s, updated_at = %s"
                " WHERE id = %s",
                (FAILED, error_code, _now(), job_id),
            )


def to_response(job: Job) -> JobResponse:
    code = job.error_code if job.status == FAILED else None
    return JobResponse(
        id=job.id,
        status=job.status,
        result=job.result,
        code=code,
        error=FRIENDLY_ERRORS.get(code) if code else None,
    )


def submit_job(messages: list[ChatMessage]) -> JobResponse:
    """Validate a chat turn, record it as queued and publish it to the worker.

    The API never runs the completion itself: this is the only place a chat
    request turns into work, so there is a single AI execution path.
    """
    turns = [
        (message.role, message.content)
        for message in messages
        if message.role in ALLOWED_ROLES
    ]
    if not turns:
        raise ChatError("bad_request")

    store = JobStore()
    job = store.create(turns)
    try:
        enqueue_job(job.id)
    except Exception:
        # the broker is down or unreachable; nothing will ever run this job
        logger.exception("Celery dispatch failed for job %s", job.id)
        store.fail(job.id, "enqueue_failed")
        raise ChatError("enqueue_failed") from None
    return to_response(job)
