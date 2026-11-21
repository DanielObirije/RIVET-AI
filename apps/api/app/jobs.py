import json
import logging
import threading
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from psycopg import Connection, errors
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.config import database_url, pool_sizes
from app.errors import FRIENDLY_ERRORS, ChatError
from app.queue import publish_job
from app.schemas import ALLOWED_ROLES, ChatMessage, JobResponse

logger = logging.getLogger(__name__)

QUEUED: Final = "queued"
RUNNING: Final = "running"
SUCCEEDED: Final = "succeeded"
FAILED: Final = "failed"

# same DDL as apps/worker/jobs.py; the two services share one table and neither
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

# one pool per process and connection string, opened on first use so importing
# the app never needs the database to be reachable
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
    retry_of: str | None = None


def job_from_row(row: DictRow) -> Job:
    stored = json.loads(row["messages"])
    return Job(
        id=row["id"],
        status=row["status"],
        messages=[(item["role"], item["content"]) for item in stored],
        result=row["result"],
        error_code=row["error_code"],
        retry_of=row["retry_of"],
    )


@contextmanager
def _transaction(dsn: str | None) -> Iterator[Connection[DictRow]]:
    """Check out one pooled connection and commit one transaction per call.

    Every caller passes its own `dsn`, so concurrent requests never share a
    handle and a test can point at its own database.
    """
    resolved = dsn or database_url()
    ensure_schema(resolved)
    with _pool(resolved).connection() as conn:
        yield conn
        conn.commit()


def conversation_turns(messages: Sequence[ChatMessage]) -> list[tuple[str, str]]:
    """The turns the model may see, dropping any client-side system message."""
    return [
        (message.role, message.content)
        for message in messages
        if message.role in ALLOWED_ROLES
    ]


def insert_job(
    conn: Connection[DictRow],
    messages: Sequence[tuple[str, str]],
    *,
    retry_of: str | None = None,
) -> Job:
    """Insert one `queued` row on the caller's connection."""
    job_id = uuid.uuid4().hex
    now = _now()
    payload = json.dumps(
        [{"role": role, "content": content} for role, content in messages]
    )
    conn.execute(
        "INSERT INTO jobs (id, status, messages, retry_of, created_at, updated_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (job_id, QUEUED, payload, retry_of, now, now),
    )
    return Job(
        id=job_id,
        status=QUEUED,
        messages=list(messages),
        result=None,
        error_code=None,
        retry_of=retry_of,
    )


def create_job(messages: Sequence[tuple[str, str]], *, dsn: str | None = None) -> Job:
    with _transaction(dsn) as conn:
        return insert_job(conn, messages)


def get_job(job_id: str, *, dsn: str | None = None) -> Job | None:
    with _transaction(dsn) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
    return job_from_row(row) if row is not None else None


def fail_job(job_id: str, error_code: str, *, dsn: str | None = None) -> None:
    with _transaction(dsn) as conn:
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
        retry_of=job.retry_of,
    )


def _publish(job: Job, *, dsn: str | None) -> JobResponse:
    try:
        publish_job(job.id)
    except Exception:
        # no queue URL, no credentials or SQS rejected the send: nothing will
        # ever run this job, so say so instead of returning a dead job id
        logger.exception("SQS publish failed for job %s", job.id)
        fail_job(job.id, "enqueue_failed", dsn=dsn)
        raise ChatError("enqueue_failed") from None
    return to_response(job)


def submit_job(
    messages: Sequence[ChatMessage], *, dsn: str | None = None
) -> JobResponse:
    """Validate a chat turn, record it as queued and publish it to the queue.

    The API never runs the completion itself: this is the only place a chat
    request turns into work, so there is a single AI execution path.
    """
    turns = conversation_turns(messages)
    if not turns:
        raise ChatError("bad_request")

    return _publish(create_job(turns, dsn=dsn), dsn=dsn)


def submit_retry(job_id: str, *, dsn: str | None = None) -> JobResponse:
    """Start a new job from an existing one, leaving the original row untouched.

    The original is locked for the length of the transaction, so two clicks in
    quick succession cannot create two retries: the second one sees the first
    retry still queued or running and returns it instead of publishing again.
    """
    with _transaction(dsn) as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id = %s FOR UPDATE", (job_id,)
        ).fetchone()
        if row is None:
            raise ChatError("not_found")

        original = job_from_row(row)
        if original.status == SUCCEEDED:
            raise ChatError("not_retryable")

        in_flight = conn.execute(
            "SELECT * FROM jobs WHERE retry_of = %s AND status IN (%s, %s)"
            " ORDER BY created_at DESC LIMIT 1",
            (original.id, QUEUED, RUNNING),
        ).fetchone()
        if in_flight is not None:
            return to_response(job_from_row(in_flight))

        retry = insert_job(conn, original.messages, retry_of=original.id)
    return _publish(retry, dsn=dsn)
