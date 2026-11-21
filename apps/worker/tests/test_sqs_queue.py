from dataclasses import replace

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from fakes import FakeSqs, message

from sqs_queue import (
    QueueUnavailable,
    ReceivedMessage,
    delete_message,
    parse_job_id,
    receive_messages,
    sqs_client,
)


def test_receive_passes_the_polling_settings(queue_settings, fake_sqs: FakeSqs) -> None:
    fake_sqs.inbox = [message("job-1")]

    received = receive_messages(settings=queue_settings, sqs=fake_sqs)

    assert received == [
        ReceivedMessage(
            message_id="msg-job-1", receipt_handle="rh-job-1", body='{"job_id": "job-1"}'
        )
    ]
    assert fake_sqs.receive_calls == [
        {
            "QueueUrl": queue_settings.queue_url,
            "MaxNumberOfMessages": queue_settings.max_messages,
            "WaitTimeSeconds": queue_settings.wait_time_seconds,
            "VisibilityTimeout": queue_settings.visibility_timeout,
        }
    ]


def test_receive_returns_nothing_when_the_queue_is_empty(
    queue_settings, fake_sqs: FakeSqs
) -> None:
    assert receive_messages(settings=queue_settings, sqs=fake_sqs) == []


def test_receive_without_a_queue_url_raises(
    queue_settings, fake_sqs: FakeSqs
) -> None:
    with pytest.raises(QueueUnavailable):
        receive_messages(settings=replace(queue_settings, queue_url=None), sqs=fake_sqs)

    assert fake_sqs.receive_calls == []


def test_receive_maps_an_aws_error(queue_settings, fake_sqs: FakeSqs) -> None:
    fake_sqs.error = EndpointConnectionError(endpoint_url="https://sqs.invalid")

    with pytest.raises(QueueUnavailable):
        receive_messages(settings=queue_settings, sqs=fake_sqs)


def test_delete_acknowledges_the_receipt_handle(
    queue_settings, fake_sqs: FakeSqs
) -> None:
    delete_message("rh-job-1", settings=queue_settings, sqs=fake_sqs)

    assert fake_sqs.deleted == ["rh-job-1"]


def test_delete_maps_an_aws_error(queue_settings, fake_sqs: FakeSqs) -> None:
    fake_sqs.error = ClientError(
        {"Error": {"Code": "ReceiptHandleIsInvalid", "Message": "gone"}},
        "DeleteMessage",
    )

    with pytest.raises(QueueUnavailable):
        delete_message("rh-job-1", settings=queue_settings, sqs=fake_sqs)


def test_parse_job_id_reads_our_message() -> None:
    assert parse_job_id('{"job_id": "job-1"}') == "job-1"


def test_a_client_can_be_built_without_credentials(
    queue_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """boto3 resolves credentials per request, so no AWS account is needed here."""
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)

    client = sqs_client(queue_settings)

    assert client.meta.region_name == "us-east-1"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "not json",
        "{}",
        '{"job_id": ""}',
        '{"job_id": 7}',
        '["job_id"]',
        '"job-1"',
    ],
)
def test_parse_job_id_rejects_anything_else(body: str) -> None:
    assert parse_job_id(body) is None
