from dataclasses import replace

import pytest
from botocore.exceptions import EndpointConnectionError
from fakes import FakeS3

from storage import (
    DEFAULT_EXPIRY_SECONDS,
    StorageUnavailable,
    asset_download_url,
    asset_metadata,
    delete_asset,
    s3_client,
    upload_asset,
)

KEY = "jobs/job-1/reply.md"


def test_upload_returns_the_metadata_a_job_row_keeps(
    storage_settings, fake_s3: FakeS3
) -> None:
    asset = upload_asset(
        KEY,
        b"hello",
        content_type="text/markdown",
        settings=storage_settings,
        client=fake_s3,
    )

    assert asset.bucket == storage_settings.bucket
    assert asset.key == KEY
    assert asset.size == 5
    assert asset.content_type == "text/markdown"
    assert asset.etag == "etag-1"
    assert asset.key in fake_s3.objects


def test_upload_grants_nothing_public(storage_settings, fake_s3: FakeS3) -> None:
    """No ACL is sent, so the bucket policy alone decides who can read."""
    upload_asset(KEY, b"hello", settings=storage_settings, client=fake_s3)

    assert set(fake_s3.put_calls[0]) == {"Bucket", "Key", "Body"}


def test_metadata_describes_a_stored_object(
    storage_settings, fake_s3: FakeS3
) -> None:
    upload_asset(
        KEY,
        b"hello",
        content_type="text/plain",
        settings=storage_settings,
        client=fake_s3,
    )

    asset = asset_metadata(KEY, settings=storage_settings, client=fake_s3)

    assert asset is not None
    assert asset.size == 5
    assert asset.content_type == "text/plain"


def test_metadata_is_none_for_a_missing_object(
    storage_settings, fake_s3: FakeS3
) -> None:
    asset = asset_metadata("jobs/nope.md", settings=storage_settings, client=fake_s3)

    assert asset is None


def test_delete_removes_the_object(storage_settings, fake_s3: FakeS3) -> None:
    upload_asset(KEY, b"hello", settings=storage_settings, client=fake_s3)

    delete_asset(KEY, settings=storage_settings, client=fake_s3)

    assert fake_s3.deleted == [KEY]
    assert KEY not in fake_s3.objects


def test_download_url_is_presigned_and_short_lived(
    storage_settings, fake_s3: FakeS3
) -> None:
    url = asset_download_url(KEY, settings=storage_settings, client=fake_s3)

    assert url.startswith("https://s3.invalid/")
    assert fake_s3.presigned == [
        {
            "operation": "get_object",
            "Params": {"Bucket": storage_settings.bucket, "Key": KEY},
            "ExpiresIn": DEFAULT_EXPIRY_SECONDS,
        }
    ]


def test_a_missing_bucket_is_an_error(storage_settings, fake_s3: FakeS3) -> None:
    settings = replace(storage_settings, bucket=None)

    with pytest.raises(StorageUnavailable):
        upload_asset(KEY, b"hello", settings=settings, client=fake_s3)

    assert fake_s3.put_calls == []


def test_an_unreachable_s3_is_a_storage_error(
    storage_settings, fake_s3: FakeS3
) -> None:
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    with pytest.raises(StorageUnavailable):
        upload_asset(KEY, b"hello", settings=storage_settings, client=fake_s3)


def test_a_failed_delete_is_a_storage_error(
    storage_settings, fake_s3: FakeS3
) -> None:
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    with pytest.raises(StorageUnavailable):
        delete_asset(KEY, settings=storage_settings, client=fake_s3)


def test_a_failed_signature_is_a_storage_error(
    storage_settings, fake_s3: FakeS3
) -> None:
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    with pytest.raises(StorageUnavailable):
        asset_download_url(KEY, settings=storage_settings, client=fake_s3)


def test_an_unreachable_s3_fails_metadata(storage_settings, fake_s3: FakeS3) -> None:
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    with pytest.raises(StorageUnavailable):
        asset_metadata(KEY, settings=storage_settings, client=fake_s3)


def test_a_client_can_be_built_without_credentials(
    storage_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)

    client = s3_client(storage_settings)

    assert client.meta.region_name == storage_settings.region
