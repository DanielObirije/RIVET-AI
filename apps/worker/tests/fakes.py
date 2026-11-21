"""Stand-ins for the boto3 clients, so no test contacts AWS."""

import io
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
    """An in-memory bucket serving the one call storage.py makes."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.get_calls: list[str] = []
        self.error: Exception | None = None

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        self.get_calls.append(kwargs["Key"])
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject"
            )
        return {"Body": io.BytesIO(stored["Body"])}

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error
