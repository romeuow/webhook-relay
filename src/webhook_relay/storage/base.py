"""BlobStorage protocol."""

from __future__ import annotations

from typing import Protocol

from webhook_relay.schemas.domain import AttachmentRef


class BlobStorage(Protocol):
    """Write-once object store for recordings and attachments."""

    def put(self, key: str, data: bytes, content_type: str) -> AttachmentRef:
        """Persist ``data`` under ``key`` and return a reference (uri, size...)."""

    def exists(self, key: str) -> bool:
        """Return ``True`` when ``key`` is already stored."""

    def healthcheck(self) -> bool:
        """Return ``True`` when the backend is reachable/writable."""
