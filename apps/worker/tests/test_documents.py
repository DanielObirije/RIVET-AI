import base64
import io

import pytest
from pypdf import PdfReader, PdfWriter

from documents import (
    AttachmentError,
    extract_pdf_text,
    prepare_jpeg_for_ai,
    process_attachment,
)
from jobs import Attachment
from samples import jpeg_bytes, pdf_bytes, png_bytes


def make_attachment(content_type: str) -> Attachment:
    return Attachment(
        id="att-1",
        filename="notes",
        content_type=content_type,
        size_bytes=0,
        s3_key="uploads/attached/att-1",
        status="attached",
        extracted_text=None,
    )


def encrypt_pdf(data: bytes, password: str) -> bytes:
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(data)).pages:
        writer.add_page(page)
    writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_text_is_extracted() -> None:
    assert "Hello PDF" in extract_pdf_text(pdf_bytes("Hello PDF"))


def test_a_pdf_without_text_reports_no_text() -> None:
    with pytest.raises(AttachmentError):
        extract_pdf_text(pdf_bytes(""))


def test_corrupt_pdfs_are_refused() -> None:
    with pytest.raises(AttachmentError):
        extract_pdf_text(b"not a pdf")


def test_a_pdf_encrypted_with_an_empty_password_is_read() -> None:
    data = encrypt_pdf(pdf_bytes("Hello PDF"), "")

    assert "Hello PDF" in extract_pdf_text(data)


def test_a_password_protected_pdf_is_refused() -> None:
    with pytest.raises(AttachmentError):
        extract_pdf_text(encrypt_pdf(pdf_bytes("Hello PDF"), "secret"))


def test_a_jpeg_becomes_a_data_url() -> None:
    data = jpeg_bytes()

    assert prepare_jpeg_for_ai(data) == (
        "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    )


def test_an_image_of_another_format_is_not_accepted_as_jpeg() -> None:
    with pytest.raises(AttachmentError):
        prepare_jpeg_for_ai(png_bytes())


def test_a_truncated_jpeg_is_refused() -> None:
    data = jpeg_bytes()

    with pytest.raises(AttachmentError):
        prepare_jpeg_for_ai(data[: len(data) // 2])


def test_the_dispatcher_uses_the_stored_content_type() -> None:
    pdf = process_attachment(make_attachment("application/pdf"), pdf_bytes("Hi"))
    jpeg = process_attachment(make_attachment("image/jpeg"), jpeg_bytes())

    assert pdf.text is not None
    assert pdf.image_data_url is None
    assert jpeg.image_data_url is not None
    assert jpeg.text is None


def test_an_unsupported_content_type_is_refused() -> None:
    with pytest.raises(AttachmentError):
        process_attachment(make_attachment("image/png"), png_bytes())
