import json

import httpx
import pytest

import chat
from settings import DeepSeekSettings

SETTINGS = DeepSeekSettings(api_key="test-key", model="deepseek-chat")


def use_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    real_client = httpx.Client

    def build(*_args, **_kwargs) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(chat.httpx, "Client", build)


def test_complete_chat_sends_the_worker_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "Hello"}}]}
        )

    use_transport(monkeypatch, handler)

    result = chat.complete_chat([("user", "Hi")], SETTINGS)

    assert result == "Hello"
    payload = captured["payload"]
    assert payload["stream"] is False
    assert payload["model"] == "deepseek-chat"
    assert payload["messages"][0] == {
        "role": "system",
        "content": chat.SYSTEM_PROMPT,
    }
    assert payload["messages"][1] == {"role": "user", "content": "Hi"}
    assert captured["authorization"] == "Bearer test-key"


def test_missing_key_is_not_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    use_transport(monkeypatch, lambda request: httpx.Response(200, json={}))

    with pytest.raises(chat.ChatUpstreamError) as raised:
        chat.complete_chat(
            [("user", "Hi")], DeepSeekSettings(api_key=None, model="deepseek-chat")
        )

    assert raised.value.code == "missing_config"
    assert raised.value.retryable is False


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(429, "rate_limit", True), (503, "unavailable", True), (400, "server_error", False)],
)
def test_upstream_status_is_classified(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str, retryable: bool
) -> None:
    use_transport(monkeypatch, lambda request: httpx.Response(status, text="nope"))

    with pytest.raises(chat.ChatUpstreamError) as raised:
        chat.complete_chat([("user", "Hi")], SETTINGS)

    assert raised.value.code == code
    assert raised.value.retryable is retryable


def test_timeout_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    use_transport(monkeypatch, handler)

    with pytest.raises(chat.ChatUpstreamError) as raised:
        chat.complete_chat([("user", "Hi")], SETTINGS)

    assert raised.value.code == "timeout"
    assert raised.value.retryable is True


def test_unreachable_upstream_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    use_transport(monkeypatch, handler)

    with pytest.raises(chat.ChatUpstreamError) as raised:
        chat.complete_chat([("user", "Hi")], SETTINGS)

    assert raised.value.code == "network"
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    "body",
    [
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"unexpected": True},
    ],
)
def test_malformed_payload_is_a_server_error(
    monkeypatch: pytest.MonkeyPatch, body: dict
) -> None:
    use_transport(monkeypatch, lambda request: httpx.Response(200, json=body))

    with pytest.raises(chat.ChatUpstreamError) as raised:
        chat.complete_chat([("user", "Hi")], SETTINGS)

    assert raised.value.code == "server_error"
    assert raised.value.retryable is False
