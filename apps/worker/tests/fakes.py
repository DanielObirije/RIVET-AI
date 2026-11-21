"""Stand-ins for the boto3 clients, so no test contacts AWS."""

import json
from typing import Any, Callable

from botocore.exceptions import ClientError


def message(job_id: str, receipt_handle: str | None = None) -> dict[str, Any]:
    """One SQS message as `receive_message` would return it."""
    return {
        "MessageId": f"msg-{job_id}",
        "ReceiptHandle": receipt_handle or f"rh-{job_id}",
        "Body": json.dumps({"job_id": job_id}),
    }


class FakeSqs:
    """Records calls, serves a canned inbox, and can fail on demand."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.receive_calls: list[dict[str, Any]] = []
        self.inbox: list[dict[str, Any]] = []
        self.error: Exception | None = None
        # hooks let a test observe state at the moment a call happens
        self.on_receive: Callable[[], None] | None = None
        self.on_delete: Callable[[str], None] | None = None

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        self.receive_calls.append(kwargs)
        limit = int(kwargs.get("MaxNumberOfMessages", 1))
        batch, self.inbox = self.inbox[:limit], self.inbox[limit:]
        if self.on_receive is not None:
            self.on_receive()
        return {"Messages": batch} if batch else {}

    def delete_message(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        if self.on_delete is not None:
            self.on_delete(kwargs["ReceiptHandle"])
        self.deleted.append(kwargs["ReceiptHandle"])
        return {}

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error


class FakeS3:
    """An in-memory bucket with the four calls storage.py needs."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.presigned: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        self._maybe_fail()
        self.put_calls.append(kwargs)
        self.objects[kwargs["Key"]] = {
            "Body": kwargs["Body"],
            "ContentType": kwargs.get("ContentType"),
        }
        return {"ETag": '"etag-1"'}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {
            "ContentLength": len(stored["Body"]),
            "ContentType": stored["ContentType"],
            "ETag": '"etag-1"',
        }

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        self.deleted.append(kwargs["Key"])
        self.objects.pop(kwargs["Key"], None)
        return {}

    def generate_presigned_url(
        self,
        operation: str,
        Params: dict[str, Any] | None = None,
        ExpiresIn: int | None = None,
    ) -> str:
        self._maybe_fail()
        self.presigned.append(
            {"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn}
        )
        params = Params or {}
        return f"https://s3.invalid/{params.get('Bucket')}/{params.get('Key')}"

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error
