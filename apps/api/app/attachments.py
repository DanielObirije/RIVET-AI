"""Attachment upload, confirmation and retention.

A browser uploads straight to a private bucket with a presigned PUT. The API
only records metadata, verifies the object and keeps the retention sweep.
"""

import logging
import re
import uuid
from dataclasses import dataclass, replace
from pathlib import PurePath
from typing import Any, Final

from psycopg import Connection
from psycopg.rows import DictRow

from app.config import (
    DOWNLOAD_URL_EXPIRY_SECONDS,
    UPLOAD_URL_EXPIRY_SECONDS,
    max_upload_bytes,
    pending_upload_ttl_hours,
)
from app.errors import ChatError
from app.jobs import ATTACHED, PENDING, transaction
from app.storage import (
    StorageUnavailable,
    copy_object,
    delete_object,
    head_object,
    presign_download,
    presign_upload,
    read_prefix,
)

logger = logging.getLogger(__name__)

CLIENT_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9_-]{8,128}")
FILENAME_MAX_LENGTH: Final = 255
SIGNATURE_LENGTH: Final = 8
SWEEP_BATCH: Final = 25

JPEG_MIME: Final = "image/jpeg"


@dataclass(frozen=True)
class FileType:
    extension: str
    content_type: str
    magic: bytes


# both JPEG spellings are stored under the canonical .jpg key
FILE_TYPES: Final[dict[str, FileType]] = {
    ".pdf": FileType(".pdf", "application/pdf", b"%PDF-"),
    ".jpg": FileType(".jpg", JPEG_MIME, b"\xff\xd8\xff"),
    ".jpeg": FileType(".jpg", JPEG_MIME, b"\xff\xd8\xff"),
}


@dataclass(frozen=True)
class Attachment:
    id: str
    owner_id: str
    filename: str
    content_type: str
    size_bytes: int
    s3_key: str
    status: str


@dataclass(frozen=True)
class UploadTarget:
    attachment: Attachment
    upload_url: str
    expires_in: int


def valid_client_id(value: str | None) -> str:
    """The browser's opaque id; it scopes attachments, it is not an account."""
    client_id = (value or "").strip()
    if not CLIENT_ID_PATTERN.fullmatch(client_id):
        raise ChatError("forbidden")
    return client_id


def attachment_from_row(row: dict[str, Any]) -> Attachment:
    return Attachment(
        id=row["id"],
        owner_id=row["owner_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        s3_key=row["s3_key"],
        status=row["status"],
    )


def _clean_filename(filename: str) -> str:
    name = PurePath(filename).name.strip()
    if not name or name in (".", ".."):
        raise ChatError("unsupported_file")
    return name[-FILENAME_MAX_LENGTH:]


def validate_upload(
    filename: str, content_type: str, size_bytes: int
) -> tuple[str, FileType]:
    """Check the declared metadata; the bytes are checked again on confirm."""
    name = _clean_filename(filename)
    file_type = FILE_TYPES.get(PurePath(name).suffix.lower())
    if file_type is None:
        raise ChatError("unsupported_file")

    declared = content_type.split(";", 1)[0].strip().lower()
    if declared != file_type.content_type:
        raise ChatError("unsupported_file")

    if size_bytes <= 0:
        raise ChatError("bad_request")
    if size_bytes > max_upload_bytes():
        raise ChatError("file_too_large")

    return name, file_type


def _owned_attachment(
    conn: Connection[DictRow],
    attachment_id: str,
    owner_id: str,
    *,
    lock: bool = False,
) -> Attachment:
    """One attachment row, refused when it is unknown or belongs to someone else."""
    query = "SELECT * FROM attachments WHERE id = %s"
    query += " FOR UPDATE" if lock else ""
    row = conn.execute(query, (attachment_id,)).fetchone()
    if row is None:
        raise ChatError("not_found")
    attachment = attachment_from_row(row)
    if attachment.owner_id != owner_id:
        raise ChatError("forbidden")
    return attachment


def begin_upload(
    filename: str,
    content_type: str,
    size_bytes: int,
    *,
    owner_id: str,
    dsn: str | None = None,
    client: Any | None = None,
) -> UploadTarget:
    """Record a pending row and hand back a short-lived direct upload URL."""
    name, file_type = validate_upload(filename, content_type, size_bytes)

    try:
        sweep_pending(dsn=dsn, client=client)
    except Exception:
        # retention must never stop a user from uploading; the lifecycle rule
        # on uploads/pending/ is the backstop
        logger.exception("Could not sweep abandoned uploads")

    attachment_id = uuid.uuid4().hex
    key = f"uploads/pending/{attachment_id}{file_type.extension}"
    try:
        upload_url = presign_upload(
            key,
            file_type.content_type,
            expires_in=UPLOAD_URL_EXPIRY_SECONDS,
            client=client,
        )
    except StorageUnavailable as exc:
        logger.error("Could not presign an upload: %s", exc)
        raise ChatError("storage_unavailable") from None

    attachment = Attachment(
        id=attachment_id,
        owner_id=owner_id,
        filename=name,
        content_type=file_type.content_type,
        size_bytes=size_bytes,
        s3_key=key,
        status=PENDING,
    )
    with transaction(dsn) as conn:
        conn.execute(
            "INSERT INTO attachments"
            " (id, owner_id, filename, content_type, size_bytes, s3_key, status,"
            " created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, now())",
            (
                attachment.id,
                attachment.owner_id,
                attachment.filename,
                attachment.content_type,
                attachment.size_bytes,
                attachment.s3_key,
                attachment.status,
            ),
        )
    return UploadTarget(
        attachment=attachment,
        upload_url=upload_url,
        expires_in=UPLOAD_URL_EXPIRY_SECONDS,
    )


def require_attachment(
    attachment_id: str, *, owner_id: str, dsn: str | None = None
) -> Attachment:
    with transaction(dsn) as conn:
        return _owned_attachment(conn, attachment_id, owner_id)


def confirm_upload(
    attachment_id: str,
    *,
    owner_id: str,
    dsn: str | None = None,
    client: Any | None = None,
) -> Attachment:
    """Verify the stored object, move it out of the pending prefix and mark it ready."""
    with transaction(dsn) as conn:
        attachment = _owned_attachment(conn, attachment_id, owner_id, lock=True)
        if attachment.status == ATTACHED:
            return attachment

        file_type = FILE_TYPES.get(PurePath(attachment.s3_key).suffix.lower())
        if file_type is None:
            raise ChatError("unsupported_file")

        try:
            stored = head_object(attachment.s3_key, client=client)
            if stored is None:
                raise ChatError("attachment_missing")
            if stored.size is None or stored.size <= 0:
                raise ChatError("bad_request")
            if stored.size > max_upload_bytes():
                raise ChatError("file_too_large")

            actual_type = (stored.content_type or "").split(";", 1)[0].lower()
            if actual_type != file_type.content_type:
                raise ChatError("unsupported_file")

            signature = read_prefix(
                attachment.s3_key, length=SIGNATURE_LENGTH, client=client
            )
            if not signature.startswith(file_type.magic):
                raise ChatError("unsupported_file")

            target_key = f"uploads/attached/{attachment_id}{file_type.extension}"
            copy_object(attachment.s3_key, target_key, client=client)
        except StorageUnavailable as exc:
            logger.error("Could not confirm attachment %s: %s", attachment_id, exc)
            raise ChatError("storage_unavailable") from None

        try:
            delete_object(attachment.s3_key, client=client)
        except StorageUnavailable as exc:
            # the pending prefix expires on its own, so this is not fatal
            logger.warning("Could not delete pending object %s: %s", attachment.s3_key, exc)

        conn.execute(
            "UPDATE attachments SET status = %s, s3_key = %s, size_bytes = %s,"
            " content_type = %s, confirmed_at = now() WHERE id = %s",
            (ATTACHED, target_key, stored.size, file_type.content_type, attachment_id),
        )
        return replace(
            attachment,
            status=ATTACHED,
            s3_key=target_key,
            size_bytes=stored.size,
            content_type=file_type.content_type,
        )


def download_url(
    attachment_id: str,
    *,
    owner_id: str,
    dsn: str | None = None,
    client: Any | None = None,
) -> tuple[str, int]:
    attachment = require_attachment(attachment_id, owner_id=owner_id, dsn=dsn)
    if attachment.status != ATTACHED:
        raise ChatError("attachment_not_ready")
    try:
        return (
            presign_download(
                attachment.s3_key,
                expires_in=DOWNLOAD_URL_EXPIRY_SECONDS,
                client=client,
            ),
            DOWNLOAD_URL_EXPIRY_SECONDS,
        )
    except StorageUnavailable as exc:
        logger.error("Could not presign a download for %s: %s", attachment_id, exc)
        raise ChatError("storage_unavailable") from None


def sweep_pending(*, dsn: str | None = None, client: Any | None = None) -> int:
    """Delete abandoned pending rows and their objects, a bounded batch per call."""
    with transaction(dsn) as conn:
        rows = conn.execute(
            "DELETE FROM attachments WHERE id IN ("
            " SELECT id FROM attachments WHERE status = %s"
            " AND created_at < now() - make_interval(hours => %s) LIMIT %s)"
            " RETURNING s3_key",
            (PENDING, pending_upload_ttl_hours(), SWEEP_BATCH),
        ).fetchall()

    for row in rows:
        try:
            delete_object(row["s3_key"], client=client)
        except StorageUnavailable as exc:
            logger.warning("Could not delete abandoned object %s: %s", row["s3_key"], exc)
    return len(rows)
