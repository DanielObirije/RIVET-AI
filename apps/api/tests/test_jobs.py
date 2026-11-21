from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.errors import FRIENDLY_ERRORS
from app.jobs import create_job, fail_job, get_job, submit_retry
from app.queue import QueueUnavailable


def test_create_job_queues_and_dispatches(
    client: TestClient, dsn: str, dispatched: list[str]
) -> None:
    response = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["result"] is None
    assert dispatched == [body["id"]]
    stored = get_job(body["id"], dsn=dsn)
    assert stored is not None
    assert stored.messages == [("user", "Hi")]


def test_create_job_drops_system_messages(client: TestClient, dsn: str) -> None:
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
    job = get_job(response.json()["id"], dsn=dsn)
    assert job is not None
    assert job.messages == [("user", "Hi")]


def test_only_system_messages_is_bad_request(client: TestClient, dsn: str) -> None:
    response = client.post(
        "/api/jobs", json={"messages": [{"role": "system", "content": "Hi"}]}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_unknown_job_is_not_found(client: TestClient, dsn: str) -> None:
    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "error": FRIENDLY_ERRORS["not_found"],
    }


def test_job_result_is_visible_once_the_worker_finishes(
    client: TestClient, dsn: str, dispatched: list[str], advance: Callable
) -> None:
    created = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    ).json()

    advance(created["id"], "running")
    running = client.get(f"/api/jobs/{created['id']}").json()
    assert running["status"] == "running"
    assert running["result"] is None

    advance(created["id"], "succeeded", "Hello there")
    finished = client.get(f"/api/jobs/{created['id']}")

    assert finished.status_code == 200
    assert finished.json()["status"] == "succeeded"
    assert finished.json()["result"] == "Hello there"
    assert finished.json()["error"] is None


def test_failed_job_reports_a_safe_error(
    client: TestClient, dsn: str, dispatched: list[str]
) -> None:
    created = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    ).json()

    fail_job(created["id"], "timeout", dsn=dsn)
    body = client.get(f"/api/jobs/{created['id']}").json()

    assert body["status"] == "failed"
    assert body["code"] == "timeout"
    assert body["error"] == FRIENDLY_ERRORS["timeout"]


def test_queue_failure_marks_the_job_failed(
    client: TestClient, dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_job_id: str) -> None:
        raise QueueUnavailable("SQS is unreachable")

    monkeypatch.setattr("app.jobs.publish_job", unreachable)

    response = client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 503
    assert response.json()["code"] == "enqueue_failed"

    with psycopg.connect(dsn) as conn:
        statuses = [row[0] for row in conn.execute("SELECT status FROM jobs")]
    assert statuses == ["failed"]


def test_concurrent_submissions_all_persist(dsn: str) -> None:
    """Each request checks out its own pooled connection; none may collide."""

    def submit(index: int) -> str:
        return create_job([("user", f"Hi {index}")], dsn=dsn).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        job_ids = list(pool.map(submit, range(24)))

    assert len(set(job_ids)) == 24
    for job_id in job_ids:
        job = get_job(job_id, dsn=dsn)
        assert job is not None
        assert job.status == "queued"


def submit_one(client: TestClient) -> dict:
    return client.post(
        "/api/jobs", json={"messages": [{"role": "user", "content": "Hi"}]}
    ).json()


def test_retry_creates_a_new_job_and_leaves_the_original(
    client: TestClient, dsn: str, dispatched: list[str]
) -> None:
    original = submit_one(client)
    fail_job(original["id"], "timeout", dsn=dsn)
    dispatched.clear()

    response = client.post(f"/api/jobs/{original['id']}/retry")

    assert response.status_code == 202
    body = response.json()
    assert body["id"] != original["id"]
    assert body["status"] == "queued"
    assert body["retry_of"] == original["id"]
    assert dispatched == [body["id"]]

    retry = get_job(body["id"], dsn=dsn)
    assert retry is not None
    assert retry.messages == [("user", "Hi")]
    assert retry.retry_of == original["id"]

    kept = get_job(original["id"], dsn=dsn)
    assert kept is not None
    assert kept.status == "failed"
    assert kept.error_code == "timeout"


def test_retry_of_a_stuck_job_starts_a_new_one(
    client: TestClient, dsn: str, dispatched: list[str]
) -> None:
    """A message that went to the DLQ leaves the row queued; retry recovers it."""
    original = submit_one(client)
    dispatched.clear()

    body = client.post(f"/api/jobs/{original['id']}/retry").json()

    assert body["retry_of"] == original["id"]
    assert dispatched == [body["id"]]
    stuck = get_job(original["id"], dsn=dsn)
    assert stuck is not None
    assert stuck.status == "queued"


def test_a_second_retry_returns_the_one_in_flight(
    client: TestClient, dsn: str, dispatched: list[str]
) -> None:
    original = submit_one(client)
    fail_job(original["id"], "server_error", dsn=dsn)
    dispatched.clear()

    first = client.post(f"/api/jobs/{original['id']}/retry").json()
    second = client.post(f"/api/jobs/{original['id']}/retry").json()

    assert second["id"] == first["id"]
    assert dispatched == [first["id"]]
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE retry_of = %s", (original["id"],)
        ).fetchall()
    assert [row[0] for row in rows] == [first["id"]]


def test_concurrent_retries_create_one_job(dsn: str, dispatched: list[str]) -> None:
    """The row lock on the original serialises two clicks into one retry."""
    original = create_job([("user", "Hi")], dsn=dsn)
    fail_job(original.id, "timeout", dsn=dsn)
    dispatched.clear()

    with ThreadPoolExecutor(max_workers=4) as pool:
        bodies = list(
            pool.map(lambda _: submit_retry(original.id, dsn=dsn), range(4))
        )

    assert len({body.id for body in bodies}) == 1
    assert dispatched == [bodies[0].id]
    with psycopg.connect(dsn) as conn:
        count = conn.execute(
            "SELECT count(*) FROM jobs WHERE retry_of = %s", (original.id,)
        ).fetchone()[0]
    assert count == 1


def test_retry_of_an_unknown_job_is_not_found(client: TestClient) -> None:
    response = client.post("/api/jobs/does-not-exist/retry")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_retry_of_a_finished_job_is_rejected(
    client: TestClient, dsn: str, dispatched: list[str], advance: Callable
) -> None:
    original = submit_one(client)
    advance(original["id"], "succeeded", "Hello there")
    dispatched.clear()

    response = client.post(f"/api/jobs/{original['id']}/retry")

    assert response.status_code == 409
    assert response.json()["code"] == "not_retryable"
    assert dispatched == []


def test_retry_publish_failure_fails_the_new_job_only(
    client: TestClient, dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = submit_one(client)
    fail_job(original["id"], "timeout", dsn=dsn)

    def unreachable(_job_id: str) -> None:
        raise QueueUnavailable("SQS is unreachable")

    monkeypatch.setattr("app.jobs.publish_job", unreachable)

    response = client.post(f"/api/jobs/{original['id']}/retry")

    assert response.status_code == 503
    assert response.json()["code"] == "enqueue_failed"

    with psycopg.connect(dsn) as conn:
        rows = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                "SELECT id, status, error_code FROM jobs"
            )
        }
    assert rows[original["id"]] == ("failed", "timeout")
    retry_errors = [value for key, value in rows.items() if key != original["id"]]
    assert retry_errors == [("failed", "enqueue_failed")]
