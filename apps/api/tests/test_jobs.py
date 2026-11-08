from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.errors import FRIENDLY_ERRORS
from app.jobs import JobStore


def test_create_job_queues_and_dispatches(
    client: TestClient, store: JobStore, dispatched: list[str]
) -> None:
    response = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["result"] is None
    assert dispatched == [body["id"]]
    stored = store.get(body["id"])
    assert stored is not None
    assert stored.messages == [("user", "Hi")]


def test_create_job_drops_system_messages(client: TestClient, store: JobStore) -> None:
    response = client.post(
        "/api/jobs",
        json={
            "messages": [
                {"role": "system", "content": "client prompt"},
                {"role": "user", "content": "Hi"},
            ]
        },
    )

    assert response.status_code == 202
    job = store.get(response.json()["id"])
    assert job is not None
    assert job.messages == [("user", "Hi")]


def test_only_system_messages_is_bad_request(
    client: TestClient, store: JobStore
) -> None:
    response = client.post(
        "/api/jobs", json={"messages": [{"role": "system", "content": "Hi"}]}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_unknown_job_is_not_found(client: TestClient, store: JobStore) -> None:
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "error": FRIENDLY_ERRORS["not_found"],
    }


def test_job_result_is_visible_once_the_worker_finishes(
    client: TestClient, store: JobStore, dispatched: list[str], advance: Callable
) -> None:
    created = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    ).json()

    advance(store, created["id"], "running")
    running = client.get(f"/api/jobs/{created['id']}").json()
    assert running["status"] == "running"
    assert running["result"] is None

    advance(store, created["id"], "succeeded", "Hello there")
    finished = client.get(f"/api/jobs/{created['id']}")

    assert finished.status_code == 200
    assert finished.json()["status"] == "succeeded"
    assert finished.json()["result"] == "Hello there"
    assert finished.json()["error"] is None


def test_failed_job_reports_a_safe_error(
    client: TestClient, store: JobStore, dispatched: list[str]
) -> None:
    created = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    ).json()

    store.fail(created["id"], "timeout")
    body = client.get(f"/api/jobs/{created['id']}").json()

    assert body["status"] == "failed"
    assert body["code"] == "timeout"
    assert body["error"] == FRIENDLY_ERRORS["timeout"]


def test_broker_failure_marks_the_job_failed(
    client: TestClient, store: JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_job_id: str) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr("app.jobs.enqueue_job", unreachable)

    response = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 503
    assert response.json()["code"] == "enqueue_failed"

    with psycopg.connect(store.dsn) as conn:
        statuses = [row[0] for row in conn.execute("SELECT status FROM jobs")]
    assert statuses == ["failed"]


def test_concurrent_submissions_all_persist(store: JobStore) -> None:
    """Each request checks out its own pooled connection; none may collide."""

    def submit(index: int) -> str:
        return store.create([("user", f"Hi {index}")]).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        job_ids = list(pool.map(submit, range(24)))

    assert len(set(job_ids)) == 24
    for job_id in job_ids:
        job = store.get(job_id)
        assert job is not None
        assert job.status == "queued"
