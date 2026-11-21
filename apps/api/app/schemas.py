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
    # at most one attachment per message, enforced by there being one field
    attachment_id: str | None = Field(default=None, max_length=64)


class JobResponse(BaseModel):
    id: str
    status: str
    result: str | None = None
    code: str | None = None
    error: str | None = None
    retry_of: str | None = None


class AttachmentRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)


class UploadUrlResponse(BaseModel):
    id: str
    upload_url: str
    expires_in: int


class AttachmentResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str


class AttachmentUrlResponse(BaseModel):
    url: str
    expires_in: int
