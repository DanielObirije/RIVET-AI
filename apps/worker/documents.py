"""Turn a stored attachment into input for the chat model.

A PDF becomes plain text; a JPEG becomes a data URL that a vision model reads.
"""

import base64
import io
from dataclasses import dataclass
from typing import Final

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from jobs import Attachment

PDF_MIME: Final = "application/pdf"
JPEG_MIME: Final = "image/jpeg"


class AttachmentError(Exception):
    """The file could not be read as the type its content type claims."""


@dataclass(frozen=True)
class PreparedAttachment:
    filename: str
    text: str | None = None
    image_data_url: str | None = None


def extract_pdf_text(data: bytes) -> str:
    """Readable text from a PDF; raises AttachmentError when there is none."""
    try:
        reader = PdfReader(io.BytesIO(data))
        # an empty password opens files that are encrypted without a secret
        if reader.is_encrypted and not reader.decrypt(""):
            raise AttachmentError("encrypted PDF")
        pages = [page.extract_text() or "" for page in reader.pages]
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError(str(exc)) from exc

    text = "\n\n".join(page.strip() for page in pages if page.strip()).strip()
    if not text:
        raise AttachmentError("no extractable text")
    return text


def prepare_jpeg_for_ai(data: bytes) -> str:
    """A data URL for a JPEG that Pillow has decoded without error."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG":
                raise AttachmentError("not a JPEG image")
            image.load()
    except AttachmentError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as exc:
        raise AttachmentError("not a JPEG image") from exc

    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{JPEG_MIME};base64,{encoded}"


def process_attachment(attachment: Attachment, data: bytes) -> PreparedAttachment:
    """Dispatch on the stored content type; raises AttachmentError otherwise."""
    if attachment.content_type == PDF_MIME:
        return PreparedAttachment(
            filename=attachment.filename, text=extract_pdf_text(data)
        )
    if attachment.content_type == JPEG_MIME:
        return PreparedAttachment(
            filename=attachment.filename,
            image_data_url=prepare_jpeg_for_ai(data),
        )
    raise AttachmentError(f"unsupported content type {attachment.content_type}")
