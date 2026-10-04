"""Download provider-hosted media with size, time and content-type guard-rails.

Provider links are short-lived and come from a third party, so we treat them as
untrusted input: the response is streamed and aborted as soon as the byte budget
is exceeded, and the declared content type must be in the allow-list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from webhook_relay.errors import MediaDownloadError, MediaTooLargeError, UnsupportedMediaTypeError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadedMedia:
    """Bytes plus the normalized content type reported by the server."""

    data: bytes
    content_type: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)


class MediaDownloader:
    """Streaming HTTP downloader. Only ``http(s)`` URLs are accepted."""

    def __init__(
        self,
        *,
        max_bytes: int,
        timeout_seconds: float,
        allowed_content_types: frozenset[str],
        client: httpx.Client | None = None,
    ) -> None:
        self._max_bytes = max_bytes
        self._allowed = allowed_content_types
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def download(self, url: str, *, content_type_hint: str | None = None) -> DownloadedMedia:
        if not url.lower().startswith(("http://", "https://")):
            raise MediaDownloadError(f"unsupported URL scheme for media download: {url[:32]}")
        try:
            with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise MediaDownloadError(
                        f"media download failed with HTTP {response.status_code}"
                    )
                content_type = _normalize(response.headers.get("content-type"), content_type_hint)
                if content_type not in self._allowed:
                    raise UnsupportedMediaTypeError(f"content type not allowed: {content_type}")

                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self._max_bytes:
                    raise MediaTooLargeError(f"declared size {declared} exceeds limit")

                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes(chunk_size=64 * 1024):
                    received += len(chunk)
                    if received > self._max_bytes:
                        raise MediaTooLargeError(f"media exceeds limit of {self._max_bytes} bytes")
                    chunks.append(chunk)
        except httpx.TimeoutException as exc:
            raise MediaDownloadError("media download timed out") from exc
        except httpx.HTTPError as exc:
            raise MediaDownloadError(f"media download error: {exc.__class__.__name__}") from exc

        data = b"".join(chunks)
        if not data:
            raise MediaDownloadError("media download returned an empty body")
        return DownloadedMedia(data=data, content_type=content_type)


def _normalize(header: str | None, hint: str | None) -> str:
    raw = header or hint or "application/octet-stream"
    return raw.split(";")[0].strip().lower()
