import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import FRIENDLY_ERRORS
from app.main import app
from app.services import deepseek


def sse_body(*deltas: str, done: bool = True) -> bytes:
    lines = [
        f'data: {json.dumps({"choices": [{"delta": {"content": delta}}]})}\n\n'
        for delta in deltas
    ]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def use_upstream(monkeypatch: pytest.MonkeyPatch, handler) -> dict:
    """Point the DeepSeek service at a mock transport and capture the request."""
    captured: dict = {}

    def build_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(deepseek, "_create_client", build_client)
    return captured


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    return TestClient(app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_api_key_is_reported_without_calling_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    response = TestClient(app).post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 500
    assert response.json() == {
        "code": "missing_config",
        "error": FRIENDLY_ERRORS["missing_config"],
    }


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


def test_streams_upstream_text_and_sends_conversation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        captured["authorization"] = request.headers["authorization"]
        captured["url"] = str(request.url)
        return httpx.Response(200, content=sse_body("Hello", " world"))

    captured = use_upstream(monkeypatch, handler)

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {
                    "id": "welcome",
                    "role": "system",
                    "content": "client-side welcome",
                    "createdAt": "2026-11-08T00:00:00.000Z",
                },
                {
                    "id": "chatcmpl-1",
                    "role": "user",
                    "content": "Hi",
                    "createdAt": "2026-11-08T00:00:01.000Z",
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "Hello world"

    payload = captured["payload"]
    assert captured["url"] == deepseek.DEEPSEEK_API_URL
    assert captured["authorization"] == "Bearer test-key"
    assert payload["model"] == "deepseek-chat"
    assert payload["stream"] is True
    assert payload["temperature"] == 0.7
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    assert payload["messages"][0]["content"] == deepseek.SYSTEM_PROMPT
    assert payload["messages"][1]["content"] == "Hi"


def test_rate_limited_upstream_becomes_rate_limit_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_upstream(monkeypatch, lambda request: httpx.Response(429, text="slow down"))

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 429
    assert response.json() == {
        "code": "rate_limit",
        "error": FRIENDLY_ERRORS["rate_limit"],
    }


def test_upstream_failure_becomes_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_upstream(monkeypatch, lambda request: httpx.Response(503, text="down"))

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 503
    assert response.json()["code"] == "unavailable"


def test_upstream_rejection_becomes_server_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_upstream(monkeypatch, lambda request: httpx.Response(401, text="bad key"))

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 502
    assert response.json()["code"] == "server_error"


def test_upstream_timeout_becomes_timeout(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    use_upstream(monkeypatch, handler)

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 504
    assert response.json()["code"] == "timeout"


def test_upstream_unreachable_becomes_network_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    use_upstream(monkeypatch, handler)

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 502
    assert response.json()["code"] == "network"


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


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", None),
        (": keep-alive", None),
        ('data: {"choices":[{"delta":{"content":"a"}}]}', "a"),
        ("data: [DONE]", deepseek._STREAM_END),
        ("data: not-json", None),
        ('data: {"choices":[]}', None),
        ('data: {"choices":[{"delta":{}}]}', None),
    ],
)
def test_parse_line(line: str, expected: object) -> None:
    assert deepseek._parse_line(line) is expected


def test_stream_interruption_keeps_partial_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_body():
        yield sse_body("Hello", done=False)
        raise httpx.ReadError("connection dropped")

    use_upstream(
        monkeypatch, lambda request: httpx.Response(200, content=broken_body())
    )

    response = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 200
    assert response.text == "Hello"
