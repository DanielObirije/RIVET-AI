from dataclasses import replace

import pytest
from botocore.exceptions import EndpointConnectionError
from fakes import FakeS3

from storage import ObjectTooLarge, StorageUnavailable, read_object, s3_client

KEY = "uploads/attached/att-1"


def test_read_object_returns_the_bytes(storage_settings, fake_s3: FakeS3) -> None:
    fake_s3.objects[KEY] = {"Body": b"hello", "ContentType": "text/plain"}

    data = read_object(KEY, max_bytes=10, settings=storage_settings, client=fake_s3)

    assert data == b"hello"


def test_read_object_refuses_an_object_over_the_limit(
    storage_settings, fake_s3: FakeS3
) -> None:
    fake_s3.objects[KEY] = {"Body": b"hello", "ContentType": "text/plain"}

    with pytest.raises(ObjectTooLarge):
        read_object(KEY, max_bytes=4, settings=storage_settings, client=fake_s3)


def test_read_object_maps_a_missing_object(
    storage_settings, fake_s3: FakeS3
) -> None:
    with pytest.raises(StorageUnavailable):
        read_object(
            "uploads/attached/missing",
            max_bytes=10,
            settings=storage_settings,
            client=fake_s3,
        )


def test_a_missing_bucket_is_an_error(storage_settings, fake_s3: FakeS3) -> None:
    settings = replace(storage_settings, bucket=None)

    with pytest.raises(StorageUnavailable):
        read_object(KEY, max_bytes=10, settings=settings, client=fake_s3)

    assert fake_s3.get_calls == []


def test_an_unreachable_s3_is_a_storage_error(
    storage_settings, fake_s3: FakeS3
) -> None:
    fake_s3.error = EndpointConnectionError(endpoint_url="https://s3.invalid")

    with pytest.raises(StorageUnavailable):
        read_object(KEY, max_bytes=10, settings=storage_settings, client=fake_s3)


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
