from typing import Annotated

from fastapi import APIRouter, Header, status

from app.attachments import (
    Attachment,
    begin_upload,
    confirm_upload,
    download_url,
    valid_client_id,
)
from app.schemas import (
    AttachmentRequest,
    AttachmentResponse,
    AttachmentUrlResponse,
    UploadUrlResponse,
)

router = APIRouter()


def _response(attachment: Attachment) -> AttachmentResponse:
    return AttachmentResponse(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        status=attachment.status,
    )


@router.post(
    "/attachments",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_upload(
    request: AttachmentRequest,
    x_client_id: Annotated[str | None, Header()] = None,
) -> UploadUrlResponse:
    """Record a pending attachment and return a direct-to-S3 PUT URL."""
    target = begin_upload(
        request.filename,
        request.content_type,
        request.size_bytes,
        owner_id=valid_client_id(x_client_id),
    )
    return UploadUrlResponse(
        id=target.attachment.id,
        upload_url=target.upload_url,
        expires_in=target.expires_in,
    )


@router.post("/attachments/{attachment_id}/confirm", response_model=AttachmentResponse)
def confirm(
    attachment_id: str,
    x_client_id: Annotated[str | None, Header()] = None,
) -> AttachmentResponse:
    """Verify the uploaded object and make the attachment usable by a chat."""
    return _response(
        confirm_upload(attachment_id, owner_id=valid_client_id(x_client_id))
    )


@router.get("/attachments/{attachment_id}/url", response_model=AttachmentUrlResponse)
def read_download_url(
    attachment_id: str,
    x_client_id: Annotated[str | None, Header()] = None,
) -> AttachmentUrlResponse:
    """A short-lived GET URL for a private attachment."""
    url, expires_in = download_url(
        attachment_id, owner_id=valid_client_id(x_client_id)
    )
    return AttachmentUrlResponse(url=url, expires_in=expires_in)
