import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import load_settings
from app.errors import ChatError
from app.schemas import ChatRequest
from app.services.deepseek import open_chat_stream

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_ROLES = frozenset({"user", "assistant"})


@router.post("/chat")
async def create_chat_stream(request: ChatRequest) -> StreamingResponse:
    messages = [message for message in request.messages if message.role in ALLOWED_ROLES]
    if not messages:
        raise ChatError("bad_request")

    stream = await open_chat_stream(messages, load_settings())

    async def body() -> AsyncIterator[str]:
        try:
            async for delta in stream.text_deltas():
                yield delta
        except httpx.HTTPError as exc:
            logger.error(
                "DeepSeek chat error: stream interrupted (%s)", type(exc).__name__
            )
        except Exception:
            logger.exception("DeepSeek chat error: stream interrupted")
        finally:
            await stream.aclose()

    return StreamingResponse(body(), media_type="text/plain; charset=utf-8")
