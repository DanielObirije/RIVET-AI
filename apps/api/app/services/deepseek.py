import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Final

import httpx

from app.config import DEEPSEEK_API_URL, UPSTREAM_TIMEOUT_SECONDS, Settings
from app.errors import ChatError, upstream_error_code
from app.schemas import ChatMessage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT: Final = """You are Rivet AI, a helpful general-purpose AI assistant.

You answer general questions, explain technical topics in plain language, help people write and improve content, summarize information, and hold natural conversations.

Stay conversational, not developmental. Do not generate, debug, or review code, and do not recommend programming tools or libraries. If someone asks for code or debugging help, explain kindly that Rivet AI is a conversational assistant rather than a coding assistant, then offer the concept in plain language instead.

Be accurate, clear, and concise. Use Markdown when it helps: short paragraphs, and lists or headings for longer answers. Ask a short clarifying question only when a request is genuinely ambiguous. If you do not know something, say so instead of guessing."""

_DATA_PREFIX: Final = "data:"
_STREAM_END: Final = object()


def _create_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS, connect=10.0)
    )


def _parse_line(line: str) -> str | object | None:
    """Return a text delta, the end sentinel, or None for lines to skip."""
    trimmed = line.strip()
    if not trimmed.startswith(_DATA_PREFIX):
        return None

    payload = trimmed[len(_DATA_PREFIX) :].strip()
    if payload == "[DONE]":
        return _STREAM_END

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return None

    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") if isinstance(first.get("delta"), dict) else {}
    content = delta.get("content")

    return content if isinstance(content, str) and content else None


class ChatStream:
    """An already-accepted upstream response whose text deltas can be iterated."""

    def __init__(self, client: httpx.AsyncClient, response: httpx.Response) -> None:
        self._client = client
        self._response = response

    async def aclose(self) -> None:
        await self._response.aclose()
        await self._client.aclose()

    async def text_deltas(self) -> AsyncIterator[str]:
        buffer = ""
        async for chunk in self._response.aiter_text():
            buffer += chunk
            lines = buffer.split("\n")
            buffer = lines.pop()

            for line in lines:
                delta = _parse_line(line)
                if delta is _STREAM_END:
                    return
                if isinstance(delta, str):
                    yield delta


async def open_chat_stream(
    messages: Sequence[ChatMessage], settings: Settings
) -> ChatStream:
    """Validate config and open the upstream stream, before any response is sent.

    Raising here keeps error mapping intact: the route can still answer with a
    proper status code, which is impossible once streaming has started.
    """
    if not settings.deepseek_api_key:
        logger.error("DeepSeek chat error: DEEPSEEK_API_KEY is not configured.")
        raise ChatError("missing_config")

    payload = {
        "model": settings.deepseek_model,
        "stream": True,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *({"role": message.role, "content": message.content} for message in messages),
        ],
    }

    client = _create_client()
    try:
        response = await client.send(
            client.build_request(
                "POST",
                DEEPSEEK_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                },
                json=payload,
            ),
            stream=True,
        )
    except httpx.TimeoutException:
        await client.aclose()
        logger.error("DeepSeek chat error: upstream timed out")
        raise ChatError("timeout") from None
    except httpx.HTTPError:
        await client.aclose()
        logger.error("DeepSeek chat error: upstream unreachable")
        raise ChatError("network") from None

    if response.status_code >= 400:
        detail = (await response.aread()).decode("utf-8", "replace")[:500]
        logger.error(
            "DeepSeek chat error: upstream responded %s %s",
            response.status_code,
            detail,
        )
        await response.aclose()
        await client.aclose()
        raise ChatError(upstream_error_code(response.status_code))

    return ChatStream(client, response)
