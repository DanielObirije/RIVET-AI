import io
from typing import Any

from botocore.exceptions import ClientError


class FakeS3:
    """An in-memory bucket with the calls app.storage makes."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.presigned: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.copied: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
            )
        return {
            "ContentLength": len(stored["Body"]),
            "ContentType": stored["ContentType"],
            "ETag": '"etag-1"',
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        stored = self.objects.get(kwargs["Key"])
        if stored is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject"
            )
        return {"Body": io.BytesIO(stored["Body"])}

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_fail()
        source = kwargs["CopySource"]["Key"]
        stored = self.objects.get(source)
        if stored is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "CopyObject"
            )
        self.objects[kwargs["Key"]] = dict(stored)
        self.copied.append((source, kwargs["Key"]))
        return {"CopyObjectResult": {}}

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
