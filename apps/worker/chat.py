import json
import logging
from collections.abc import Sequence
from typing import Final

import httpx

from settings import UPSTREAM_TIMEOUT_SECONDS, DeepSeekSettings, deepseek_api_url

logger = logging.getLogger(__name__)

SYSTEM_PROMPT: Final = """You are Rivet AI, a helpful general-purpose AI assistant.

You answer general questions, explain technical topics in plain language, help people write and improve content, summarize information, and hold natural conversations.

Stay conversational, not developmental. Do not generate, debug, or review code, and do not recommend programming tools or libraries. If someone asks for code or debugging help, explain kindly that Rivet AI is a conversational assistant rather than a coding assistant, then offer the concept in plain language instead.

Be accurate, clear, and concise. Use Markdown when it helps: short paragraphs, and lists or headings for longer answers. Ask a short clarifying question only when a request is genuinely ambiguous. If you do not know something, say so instead of guessing."""


class ChatUpstreamError(Exception):
    """A failed completion; `code` is one of the codes the API already knows."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def classify_status(status: int) -> str:
    if status in (402, 429):
        return "rate_limit"
    if status >= 500:
        return "unavailable"
    return "server_error"


def build_payload(
    messages: Sequence[tuple[str, str]], model: str, *, stream: bool
) -> dict[str, object]:
    return {
        "model": model,
        "stream": stream,
        "temperature": 0.7,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *({"role": role, "content": content} for role, content in messages),
        ],
    }


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _require_api_key(settings: DeepSeekSettings) -> str:
    if not settings.api_key:
        logger.error("DeepSeek chat error: DEEPSEEK_API_KEY is not configured.")
        raise ChatUpstreamError("missing_config", retryable=False)
    return settings.api_key


def complete_chat(
    messages: Sequence[tuple[str, str]], settings: DeepSeekSettings
) -> str:
    """Run one non-streaming completion and return the assistant's text."""
    api_key = _require_api_key(settings)
    payload = build_payload(messages, settings.model, stream=False)

    try:
        with httpx.Client(
            timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS, connect=10.0)
        ) as client:
            response = client.post(
                deepseek_api_url(), headers=_headers(api_key), json=payload
            )
    except httpx.TimeoutException:
        logger.error("DeepSeek chat error: upstream timed out")
        raise ChatUpstreamError("timeout", retryable=True) from None
    except httpx.HTTPError:
        logger.error("DeepSeek chat error: upstream unreachable")
        raise ChatUpstreamError("network", retryable=True) from None

    if response.status_code >= 400:
        detail = response.text[:500]
        logger.error(
            "DeepSeek chat error: upstream responded %s %s",
            response.status_code,
            detail,
        )
        code = classify_status(response.status_code)
        raise ChatUpstreamError(code, retryable=code in ("rate_limit", "unavailable"))

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        logger.error("DeepSeek chat error: malformed upstream payload")
        raise ChatUpstreamError("server_error", retryable=False) from None

    if not isinstance(content, str) or not content:
        logger.error("DeepSeek chat error: empty upstream content")
        raise ChatUpstreamError("server_error", retryable=False) from None

    return content
