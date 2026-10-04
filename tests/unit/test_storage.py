"""Local and S3 blob storage adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from webhook_relay.errors import StorageError
from webhook_relay.storage.local import LocalBlobStorage, extension_for
from webhook_relay.storage.s3 import S3BlobStorage


@pytest.mark.parametrize(
    ("content_type", "ext"),
    [("audio/mpeg", ".mp3"), ("audio/ogg; codecs=opus", ".ogg"), ("video/mp4", ".bin")],
)
def test_extension_for(content_type: str, ext: str) -> None:
    assert extension_for(content_type) == ext


class TestLocalBlobStorage:
    def test_put_writes_file_and_returns_ref(self, tmp_path: Path) -> None:
        storage = LocalBlobStorage(tmp_path / "blobs")
        ref = storage.put("voice/call_1/recording", b"abc", "audio/mpeg")
        assert ref.key == "voice/call_1/recording.mp3"
        assert ref.size_bytes == 3
        assert ref.content_type == "audio/mpeg"
        assert ref.uri.startswith("file://")
        assert (storage.root / ref.key).read_bytes() == b"abc"
        assert storage.exists("voice/call_1/recording")
        assert not storage.exists("voice/call_1/other")
        assert not list(storage.root.rglob("*.tmp"))

    def test_put_overwrites_same_key(self, tmp_path: Path) -> None:
        storage = LocalBlobStorage(tmp_path)
        storage.put("k", b"one", "audio/mpeg")
        ref = storage.put("k", b"two", "audio/mpeg")
        assert (storage.root / ref.key).read_bytes() == b"two"
        assert len(list(storage.root.iterdir())) == 1

    def test_keys_cannot_escape_root(self, tmp_path: Path) -> None:
        storage = LocalBlobStorage(tmp_path / "blobs")
        ref = storage.put("../../etc/passwd", b"x", "audio/mpeg")
        assert (storage.root / ref.key).exists()
        assert storage.root in (storage.root / ref.key).resolve().parents

    def test_empty_key_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(StorageError, match="empty"):
            LocalBlobStorage(tmp_path).put("/./", b"x", "audio/mpeg")

    def test_healthcheck(self, tmp_path: Path) -> None:
        assert LocalBlobStorage(tmp_path).healthcheck()

    def test_write_failure_is_wrapped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        storage = LocalBlobStorage(tmp_path)

        def boom(*_: Any, **__: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_bytes", boom)
        with pytest.raises(StorageError, match="disk full"):
            storage.put("k", b"x", "audio/mpeg")


class StubS3Client:
    def __init__(self, *, fail: bool = False) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.fail = fail

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("AccessDenied")
        self.objects[kwargs["Key"]] = kwargs
        return {"ETag": "x"}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs["Key"] not in self.objects:
            raise RuntimeError("404")
        return {}

    def head_bucket(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("NoSuchBucket")
        return {}


class TestS3BlobStorage:
    def test_put_uploads_with_metadata(self) -> None:
        client = StubS3Client()
        storage = S3BlobStorage("bucket", client, prefix="/recordings/")
        ref = storage.put("voice/call_1/recording", b"abc", "audio/mpeg")
        assert ref.key == "recordings/voice/call_1/recording.mp3"
        assert ref.uri == "s3://bucket/recordings/voice/call_1/recording.mp3"
        stored = client.objects[ref.key]
        assert stored["Bucket"] == "bucket"
        assert stored["ContentType"] == "audio/mpeg"
        assert stored["ContentLength"] == 3
        assert storage.exists(ref.key)
        assert not storage.exists("missing")
        assert storage.healthcheck()

    def test_errors_are_wrapped(self) -> None:
        storage = S3BlobStorage("bucket", StubS3Client(fail=True))
        with pytest.raises(StorageError, match="AccessDenied"):
            storage.put("k", b"x", "audio/mpeg")
        assert not storage.healthcheck()
        with pytest.raises(StorageError, match="empty"):
            storage.put("..", b"x", "audio/mpeg")

    def test_requires_bucket(self) -> None:
        with pytest.raises(ValueError, match="bucket"):
            S3BlobStorage("", StubS3Client())

    def test_from_settings_builds_boto3_client_offline(self) -> None:
        storage = S3BlobStorage.from_settings(
            "bucket", endpoint_url="http://localhost:9000", region="us-east-1"
        )
        assert isinstance(storage, S3BlobStorage)
