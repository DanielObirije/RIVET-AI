from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from jobs import JobStore


def test_store_requeue_then_reclaim(
    store: JobStore, queue_job: Callable[..., str]
) -> None:
    job_id = queue_job(store)

    claimed = store.start(job_id)
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.attempts == 1

    store.requeue(job_id)
    requeued = store.get(job_id)
    assert requeued is not None
    assert requeued.status == "queued"

    reclaimed = store.start(job_id)
    assert reclaimed is not None
    assert reclaimed.attempts == 2


def test_store_ignores_a_finished_job(
    store: JobStore, queue_job: Callable[..., str]
) -> None:
    job_id = queue_job(store)
    store.succeed(job_id, "done")

    assert store.start(job_id) is None


def test_concurrent_claims_are_serialised(
    store: JobStore, queue_job: Callable[..., str]
) -> None:
    """The conditional UPDATE takes a row lock, so no attempt count is lost."""
    job_id = queue_job(store)

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: store.start(job_id), range(8)))

    assert all(job is not None for job in claimed)
    assert sorted(job.attempts for job in claimed if job) == list(range(1, 9))

    final = store.get(job_id)
    assert final is not None
    assert final.attempts == 8
