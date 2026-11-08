from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobStore


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_returns_a_queued_job_and_dispatches_it(
    client: TestClient, store: JobStore, dispatched: list[str]
) -> None:
    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["result"] is None
    assert dispatched == [body["id"]]

    stored = store.get(body["id"])
    assert stored is not None
    assert stored.messages == [("user", "Hi")]


def test_chat_drops_client_side_system_messages(
    client: TestClient, store: JobStore, dispatched: list[str]
) -> None:
    response = client.post(
        "/api/chat",
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


def test_empty_message_list_is_bad_request(client: TestClient) -> None:
    response = client.post("/api/chat", json={"messages": []})

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_malformed_json_is_bad_request(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_message_without_content_is_bad_request(client: TestClient) -> None:
    response = client.post("/api/chat", json={"messages": [{"role": "user"}]})

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_only_system_messages_is_bad_request(client: TestClient) -> None:
    response = client.post(
        "/api/chat", json={"messages": [{"role": "system", "content": "Hi"}]}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_chat_needs_no_model_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, dispatched: list[str]
) -> None:
    """The API owns no model call, so it must not need the DeepSeek key."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 202


def test_chat_result_comes_from_the_job(
    client: TestClient, store: JobStore, dispatched: list[str], advance: Callable
) -> None:
    job_id = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    ).json()["id"]

    advance(store, job_id, "succeeded", "Hello there")
    body = client.get(f"/api/jobs/{job_id}").json()

    assert body["status"] == "succeeded"
    assert body["result"] == "Hello there"


def test_preflight_allows_the_next_origin(client: TestClient) -> None:
    response = client.options(
        "/api/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
