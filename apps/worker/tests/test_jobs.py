from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import psycopg

from jobs import get_job, requeue_job, start_job, succeed_job

RECLAIM_WINDOW_SECONDS = 120


def test_requeue_then_reclaim(dsn: str, queue_job: Callable[..., str]) -> None:
    job_id = queue_job()

    claimed = start_job(job_id, dsn=dsn)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.attempts == 1

    requeue_job(job_id, dsn=dsn)
    requeued = get_job(job_id, dsn=dsn)
    assert requeued is not None
    assert requeued.status == "queued"

    reclaimed = start_job(job_id, dsn=dsn)
    assert reclaimed is not None
    assert reclaimed.attempts == 2


def test_start_ignores_a_finished_job(dsn: str, queue_job: Callable[..., str]) -> None:
    job_id = queue_job()
    succeed_job(job_id, "done", dsn=dsn)

    assert start_job(job_id, dsn=dsn) is None


def test_only_one_concurrent_claim_wins(
    dsn: str, queue_job: Callable[..., str]
) -> None:
    """Two workers handed the same message must not both run the job."""
    job_id = queue_job()

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: start_job(job_id, dsn=dsn), range(8)))

    winners = [job for job in claimed if job is not None]
    assert len(winners) == 1
    assert winners[0].attempts == 1

    final = get_job(job_id, dsn=dsn)
    assert final is not None
    assert final.attempts == 1


def test_a_running_job_is_owned_until_its_lease_expires(
    dsn: str, queue_job: Callable[..., str]
) -> None:
    """A duplicate delivery inside the visibility window is refused."""
    job_id = queue_job()
    assert start_job(job_id, dsn=dsn) is not None

    assert start_job(job_id, dsn=dsn, owned_for=RECLAIM_WINDOW_SECONDS) is None


def test_a_stale_running_job_is_reclaimed(
    dsn: str, queue_job: Callable[..., str]
) -> None:
    """A worker killed mid-job leaves the row running; redelivery must reclaim it."""
    job_id = queue_job()
    assert start_job(job_id, dsn=dsn) is not None

    with psycopg.connect(dsn) as conn:
        conn.execute(
            "UPDATE jobs SET updated_at = now() - interval '10 minutes' WHERE id = %s",
            (job_id,),
        )

    reclaimed = start_job(job_id, dsn=dsn, owned_for=RECLAIM_WINDOW_SECONDS)

    assert reclaimed is not None
    assert reclaimed.status == "running"
    assert reclaimed.attempts == 2
