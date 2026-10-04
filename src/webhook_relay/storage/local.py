"""Filesystem blob storage for demo mode and tests."""

from __future__ import annotations

import os
from pathlib import Path

from webhook_relay.errors import StorageError
from webhook_relay.schemas.domain import AttachmentRef

EXTENSION_BY_TYPE = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "application/octet-stream": ".bin",
}


def extension_for(content_type: str) -> str:
    """Pick a file extension for a content type (defaults to ``.bin``)."""
    return EXTENSION_BY_TYPE.get(content_type.split(";")[0].strip().lower(), ".bin")


class LocalBlobStorage:
    """Stores blobs under ``root``; keys may contain ``/`` to build sub-directories."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def put(self, key: str, data: bytes, content_type: str) -> AttachmentRef:
        path = self._path_for(key, content_type)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)  # atomic on POSIX: readers never see a partial file
        except OSError as exc:
            raise StorageError(f"failed to write blob {key}: {exc}") from exc
        return AttachmentRef(
            key=str(path.relative_to(self._root)),
            uri=path.as_uri(),
            content_type=content_type,
            size_bytes=len(data),
        )

    def exists(self, key: str) -> bool:
        candidates = list(self._root.glob(f"{_sanitize(key)}.*"))
        return any(c.is_file() and not c.name.endswith(".tmp") for c in candidates)

    def healthcheck(self) -> bool:
        return self._root.is_dir() and os.access(self._root, os.W_OK)

    def _path_for(self, key: str, content_type: str) -> Path:
        safe = _sanitize(key)
        path = (self._root / safe).with_suffix(extension_for(content_type))
        if self._root not in path.resolve().parents:
            raise StorageError(f"blob key escapes storage root: {key}")
        return path


def _sanitize(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise StorageError("blob key must not be empty")
    return "/".join(parts)
