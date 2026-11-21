import json
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import SqsSettings, load_sqs_settings
from app.queue import QueueUnavailable, publish_job, sqs_client

QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/rivet-jobs"


def settings(queue_url: str | None = QUEUE_URL) -> SqsSettings:
    return SqsSettings(queue_url=queue_url, region="us-east-1", endpoint_url=None)


class FakeSqs:
    """Stands in for a boto3 SQS client; records sends and can fail on demand."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.error = error

    def send_message(self, **kwargs: Any) -> dict[str, str]:
        if self.error is not None:
            raise self.error
        self.sent.append(kwargs)
        return {"MessageId": f"msg-{len(self.sent)}"}


def test_publish_sends_only_the_job_id() -> None:
    sqs = FakeSqs()

    publish_job("job-1", settings=settings(), sqs=sqs)

    assert sqs.sent == [
        {"QueueUrl": QUEUE_URL, "MessageBody": json.dumps({"job_id": "job-1"})}
    ]
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"job_id": "job-1"}


def test_publish_without_a_queue_url_is_an_error() -> None:
    """No queue configured must fail loudly; a queued row nobody reads is worse."""
    sqs = FakeSqs()

    with pytest.raises(QueueUnavailable):
        publish_job("job-1", settings=settings(queue_url=None), sqs=sqs)

    assert sqs.sent == []


def test_publish_maps_an_aws_error() -> None:
    error = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "SendMessage"
    )

    with pytest.raises(QueueUnavailable):
        publish_job("job-1", settings=settings(), sqs=FakeSqs(error))


def test_publish_maps_a_connection_error() -> None:
    error = EndpointConnectionError(endpoint_url=QUEUE_URL)

    with pytest.raises(QueueUnavailable):
        publish_job("job-1", settings=settings(), sqs=FakeSqs(error))


def test_publish_needs_no_aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_REGION",
        "SQS_QUEUE_URL",
        "SQS_ENDPOINT_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    def explode(*_: object, **__: object) -> None:
        raise AssertionError("no SQS client should be built when one is injected")

    monkeypatch.setattr("app.queue.boto3.client", explode)
    sqs = FakeSqs()

    publish_job("job-1", settings=settings(), sqs=sqs)

    assert len(sqs.sent) == 1


def test_queue_settings_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQS_QUEUE_URL", QUEUE_URL)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.delenv("SQS_ENDPOINT_URL", raising=False)

    assert load_sqs_settings() == SqsSettings(
        queue_url=QUEUE_URL, region="eu-west-1", endpoint_url=None
    )


def test_an_empty_queue_url_counts_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQS_QUEUE_URL", "   ")

    assert load_sqs_settings().queue_url is None


def test_a_client_can_be_built_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boto3 resolves credentials per request, so no AWS account is needed here."""
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)

    client = sqs_client(settings())

    assert client.meta.region_name == "us-east-1"
