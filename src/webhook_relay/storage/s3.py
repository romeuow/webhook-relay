"""S3-compatible blob storage (AWS S3, MinIO, LocalStack) via boto3."""

from __future__ import annotations

from typing import Any, Protocol

from webhook_relay.errors import StorageError
from webhook_relay.schemas.domain import AttachmentRef
from webhook_relay.storage.local import extension_for


class S3ClientLike(Protocol):
    """Subset of the boto3 S3 client used here (tests inject a stub)."""

    def put_object(self, **kwargs: Any) -> Any: ...

    def head_object(self, **kwargs: Any) -> Any: ...

    def head_bucket(self, **kwargs: Any) -> Any: ...


class S3BlobStorage:
    """Writes objects to ``bucket``; ``endpoint_url`` makes it work against MinIO/LocalStack."""

    def __init__(self, bucket: str, client: S3ClientLike, *, prefix: str = "") -> None:
        if not bucket:
            raise ValueError("bucket must not be empty")
        self._bucket = bucket
        self._client = client
        self._prefix = prefix.strip("/")

    @classmethod
    def from_settings(
        cls,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        prefix: str = "",
    ) -> S3BlobStorage:
        """Build a real boto3 client (credentials come from the standard AWS credential chain)."""
        import boto3

        client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)
        return cls(bucket, client, prefix=prefix)

    def put(self, key: str, data: bytes, content_type: str) -> AttachmentRef:
        object_key = self._object_key(key, content_type)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type,
                ContentLength=len(data),
            )
        except Exception as exc:  # boto3 raises botocore.exceptions.ClientError and friends
            raise StorageError(f"failed to upload {object_key}: {exc}") from exc
        return AttachmentRef(
            key=object_key,
            uri=f"s3://{self._bucket}/{object_key}",
            content_type=content_type,
            size_bytes=len(data),
        )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception:
            return False
        return True

    def healthcheck(self) -> bool:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            return False
        return True

    def _object_key(self, key: str, content_type: str) -> str:
        clean = "/".join(p for p in key.split("/") if p not in ("", ".", ".."))
        if not clean:
            raise StorageError("blob key must not be empty")
        full = f"{self._prefix}/{clean}" if self._prefix else clean
        return full + extension_for(content_type)
