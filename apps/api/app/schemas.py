from typing import Final

from pydantic import BaseModel, Field

# only real conversation turns are forwarded; a client-side system message is
# replaced by the server prompt
ALLOWED_ROLES: Final = frozenset({"user", "assistant"})


class ChatMessage(BaseModel):
    role: str = Field(min_length=1, max_length=32)
    content: str = Field(max_length=100_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=300)


class JobResponse(BaseModel):
    id: str
    status: str
    result: str | None = None
    code: str | None = None
    error: str | None = None
