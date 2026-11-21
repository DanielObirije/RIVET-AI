import psycopg
import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient

from app.attachments import sweep_pending
from app.jobs import get_job, submit_retry
from fakes import FakeS3

CLIENT = "client-0123456789"
OTHER_CLIENT = "client-9876543210"
HEADERS = {"X-Client-Id": CLIENT}
PDF_BODY = b"%PDF-1.7\nhello attachment"
JPEG_BODY = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def start_upload(
    client: TestClient,
    *,
    filename: str = "notes.pdf",
    content_type: str = "application/pdf",
    size_bytes: int = len(PDF_BODY),
    headers: dict[str, str] | None = HEADERS,
):
    return client.post(
        "/api/attachments",
        json={
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size_bytes,
        },
        headers=headers,
    )


def store_uploaded_object(
    fake_s3: FakeS3, body: bytes = PDF_BODY, content_type: str = "application/pdf"
) -> str:
    key = fake_s3.presigned[-1]["Params"]["Key"]
    fake_s3.objects[key] = {"Body": body, "ContentType": content_type}
    return key


def confirmed_attachment(client: TestClient, fake_s3: FakeS3) -> str:
    created = start_upload(client).json()
    store_uploaded_object(fake_s3)
    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )
    assert response.status_code == 200
    return created["id"]


def test_upload_is_presigned_private_and_pending(
    client: TestClient, fake_s3: FakeS3, dsn: str
) -> None:
    response = start_upload(client)

    assert response.status_code == 201
    body = response.json()
    assert body["upload_url"].startswith("https://s3.invalid/")
    assert body["expires_in"] == 300

    call = fake_s3.presigned[-1]
    assert call["operation"] == "put_object"
    assert call["Params"] == {
        "Bucket": "rivet-assets",
        "Key": f"uploads/pending/{body['id']}.pdf",
        "ContentType": "application/pdf",
    }

    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT status, owner_id FROM attachments WHERE id = %s", (body["id"],)
        ).fetchone()
    assert row == ("pending", CLIENT)


def test_confirm_moves_the_object_and_marks_it_attached(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()
    pending_key = store_uploaded_object(fake_s3)

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "attached"
    assert body["filename"] == "notes.pdf"
    assert body["size_bytes"] == len(PDF_BODY)
    assert fake_s3.copied == [
        (pending_key, f"uploads/attached/{created['id']}.pdf")
    ]
    assert pending_key not in fake_s3.objects
    assert f"uploads/attached/{created['id']}.pdf" in fake_s3.objects


def test_confirm_is_idempotent(client: TestClient, fake_s3: FakeS3) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)

    again = client.post(f"/api/attachments/{attachment_id}/confirm", headers=HEADERS)

    assert again.status_code == 200
    assert len(fake_s3.copied) == 1


@pytest.mark.parametrize("filename", ["photo.jpg", "photo.jpeg"])
def test_a_jpeg_upload_is_confirmed_under_the_canonical_extension(
    client: TestClient, fake_s3: FakeS3, filename: str
) -> None:
    created = start_upload(
        client,
        filename=filename,
        content_type="image/jpeg",
        size_bytes=len(JPEG_BODY),
    ).json()
    pending_key = store_uploaded_object(
        fake_s3, body=JPEG_BODY, content_type="image/jpeg"
    )

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["content_type"] == "image/jpeg"
    assert fake_s3.copied == [
        (pending_key, f"uploads/attached/{created['id']}.jpg")
    ]


def test_confirm_rejects_a_file_whose_signature_does_not_match(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()
    store_uploaded_object(fake_s3, body=b"plain text, not a pdf")

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_file"
    assert fake_s3.copied == []


def test_confirm_rejects_an_object_over_the_limit(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client, size_bytes=10).json()
    store_uploaded_object(fake_s3, body=b"%PDF-" + b"x" * (1024 * 1024))

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 400
    assert response.json()["code"] == "file_too_large"


def test_confirm_reports_a_missing_object(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 404
    assert response.json()["code"] == "attachment_missing"


def test_another_client_cannot_confirm(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()
    store_uploaded_object(fake_s3)

    response = client.post(
        f"/api/attachments/{created['id']}/confirm",
        headers={"X-Client-Id": OTHER_CLIENT},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_a_missing_client_id_cannot_create_an_upload(client: TestClient) -> None:
    response = start_upload(client, headers=None)

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(
    ("filename", "content_type", "size_bytes", "code"),
    [
        ("run.exe", "application/pdf", 10, "unsupported_file"),
        ("notes.pdf", "image/jpeg", 10, "unsupported_file"),
        ("notes.pdf", "application/pdf", 2 * 1024 * 1024, "file_too_large"),
        ("notes.pdf", "application/pdf", 0, "bad_request"),
    ],
)
def test_bad_upload_metadata_is_refused(
    client: TestClient,
    filename: str,
    content_type: str,
    size_bytes: int,
    code: str,
) -> None:
    response = start_upload(
        client, filename=filename, content_type=content_type, size_bytes=size_bytes
    )

    assert response.status_code == 400
    assert response.json()["code"] == code


def test_a_storage_failure_is_a_503(
    client: TestClient, fake_s3: FakeS3
) -> None:
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    response = start_upload(client)

    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"


def test_chat_with_a_pending_attachment_is_refused(
    client: TestClient, fake_s3: FakeS3, dispatched: list[str]
) -> None:
    created = start_upload(client).json()

    response = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Summarize this"}],
            "attachment_id": created["id"],
        },
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "attachment_not_ready"
    assert dispatched == []


def test_chat_with_an_attached_file_creates_the_job(
    client: TestClient, fake_s3: FakeS3, dsn: str, dispatched: list[str]
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)

    response = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Summarize this"}],
            "attachment_id": attachment_id,
        },
        headers=HEADERS,
    )

    assert response.status_code == 202
    job = get_job(response.json()["id"], dsn=dsn)
    assert job is not None
    assert job.attachment_id == attachment_id
    assert dispatched == [job.id]


def test_chat_cannot_use_someone_elses_attachment(
    client: TestClient, fake_s3: FakeS3, dispatched: list[str]
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)

    response = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Summarize this"}],
            "attachment_id": attachment_id,
        },
        headers={"X-Client-Id": OTHER_CLIENT},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert dispatched == []


def test_chat_without_a_client_id_cannot_use_an_attachment(
    client: TestClient, fake_s3: FakeS3, dispatched: list[str]
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)

    response = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Summarize this"}],
            "attachment_id": attachment_id,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert dispatched == []


def test_download_url_is_presigned_for_the_owner(
    client: TestClient, fake_s3: FakeS3
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)

    response = client.get(
        f"/api/attachments/{attachment_id}/url", headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://s3.invalid/")
    assert fake_s3.presigned[-1]["operation"] == "get_object"
    assert fake_s3.presigned[-1]["ExpiresIn"] == 300


def test_another_client_cannot_get_a_download_url(
    client: TestClient, fake_s3: FakeS3
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)

    response = client.get(
        f"/api/attachments/{attachment_id}/url",
        headers={"X-Client-Id": OTHER_CLIENT},
    )

    assert response.status_code == 403


def test_retry_reuses_the_original_attachment(
    client: TestClient, fake_s3: FakeS3, dsn: str, advance
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)
    created = client.post(
        "/api/chat",
        json={
            "messages": [{"role": "user", "content": "Summarize this"}],
            "attachment_id": attachment_id,
        },
        headers=HEADERS,
    ).json()
    advance(created["id"], "failed")

    retried = submit_retry(created["id"], dsn=dsn)

    assert retried.id != created["id"]
    retry_job = get_job(retried.id, dsn=dsn)
    assert retry_job is not None
    assert retry_job.attachment_id == attachment_id


def test_sweep_deletes_abandoned_pending_rows_and_objects(
    client: TestClient, fake_s3: FakeS3, dsn: str
) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO attachments"
            " (id, owner_id, filename, content_type, size_bytes, s3_key, status,"
            " created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'pending', now() - interval '2 days')",
            (
                "abandoned",
                CLIENT,
                "old.pdf",
                "application/pdf",
                10,
                "uploads/pending/abandoned.pdf",
            ),
        )

    removed = sweep_pending(dsn=dsn, client=fake_s3)

    assert removed == 1
    assert fake_s3.deleted == ["uploads/pending/abandoned.pdf"]
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT id FROM attachments WHERE id = 'abandoned'"
        ).fetchone()
    assert row is None


def test_confirm_reports_storage_unavailable(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()
    store_uploaded_object(fake_s3)
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"


def test_confirm_rejects_a_mismatched_stored_content_type(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()
    store_uploaded_object(fake_s3, content_type="text/plain")

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_file"


def test_a_pending_attachment_has_no_download_url(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()

    response = client.get(
        f"/api/attachments/{created['id']}/url", headers=HEADERS
    )

    assert response.status_code == 409
    assert response.json()["code"] == "attachment_not_ready"


def test_a_download_signing_failure_is_a_503(
    client: TestClient, fake_s3: FakeS3
) -> None:
    attachment_id = confirmed_attachment(client, fake_s3)
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    response = client.get(f"/api/attachments/{attachment_id}/url", headers=HEADERS)

    assert response.status_code == 503
    assert response.json()["code"] == "storage_unavailable"


def test_an_unknown_attachment_is_not_found(client: TestClient) -> None:
    confirm = client.post("/api/attachments/missing/confirm", headers=HEADERS)
    url = client.get("/api/attachments/missing/url", headers=HEADERS)

    assert confirm.status_code == 404
    assert confirm.json()["code"] == "not_found"
    assert url.status_code == 404
    assert url.json()["code"] == "not_found"


def test_a_whitespace_filename_is_refused(client: TestClient) -> None:
    response = start_upload(client, filename="   ")

    assert response.status_code == 400
    assert response.json()["code"] == "unsupported_file"


def test_a_short_client_id_is_refused(client: TestClient) -> None:
    response = start_upload(client, headers={"X-Client-Id": "short"})

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_sweep_removes_the_row_even_when_the_delete_fails(
    client: TestClient, fake_s3: FakeS3, dsn: str
) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO attachments"
            " (id, owner_id, filename, content_type, size_bytes, s3_key, status,"
            " created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, 'pending', now() - interval '2 days')",
            (
                "abandoned",
                CLIENT,
                "old.pdf",
                "application/pdf",
                10,
                "uploads/pending/abandoned.pdf",
            ),
        )
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    removed = sweep_pending(dsn=dsn, client=fake_s3)

    assert removed == 1
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT id FROM attachments WHERE id = 'abandoned'"
        ).fetchone()
    assert row is None


def test_confirm_rejects_an_empty_object(
    client: TestClient, fake_s3: FakeS3
) -> None:
    created = start_upload(client).json()
    store_uploaded_object(fake_s3, body=b"")

    response = client.post(
        f"/api/attachments/{created['id']}/confirm", headers=HEADERS
    )

    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"
