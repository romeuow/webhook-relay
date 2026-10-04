"""Guarded media downloader (respx-mocked, no network)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import respx

from webhook_relay.errors import MediaDownloadError, MediaTooLargeError, UnsupportedMediaTypeError
from webhook_relay.storage.download import MediaDownloader

URL = "https://cdn.provider.example.com/media/a.mp3"


@pytest.fixture
def downloader() -> Iterator[MediaDownloader]:
    dl = MediaDownloader(
        max_bytes=1000, timeout_seconds=1, allowed_content_types=frozenset({"audio/mpeg"})
    )
    yield dl
    dl.close()


@respx.mock
def test_download_success(downloader: MediaDownloader) -> None:
    respx.get(URL).respond(200, content=b"x" * 500, headers={"content-type": "audio/mpeg; q=1"})
    media = downloader.download(URL)
    assert media.size_bytes == 500
    assert media.content_type == "audio/mpeg"


@respx.mock
def test_download_falls_back_to_hint_when_header_missing(downloader: MediaDownloader) -> None:
    respx.get(URL).respond(200, content=b"abc")
    media = downloader.download(URL, content_type_hint="audio/mpeg")
    assert media.content_type == "audio/mpeg"


@respx.mock
def test_disallowed_content_type(downloader: MediaDownloader) -> None:
    respx.get(URL).respond(200, content=b"<html>", headers={"content-type": "text/html"})
    with pytest.raises(UnsupportedMediaTypeError):
        downloader.download(URL)


@respx.mock
def test_declared_size_over_limit(downloader: MediaDownloader) -> None:
    respx.get(URL).respond(
        200, content=b"x", headers={"content-type": "audio/mpeg", "content-length": "5000"}
    )
    with pytest.raises(MediaTooLargeError, match="declared"):
        downloader.download(URL)


@respx.mock
def test_streamed_size_over_limit(downloader: MediaDownloader) -> None:
    def stream() -> Iterator[bytes]:
        for _ in range(20):
            yield b"x" * 100

    respx.get(URL).mock(
        return_value=httpx.Response(
            200, stream=httpx.ByteStream(b"".join(stream())), headers={"content-type": "audio/mpeg"}
        )
    )
    with pytest.raises(MediaTooLargeError, match="exceeds limit"):
        downloader.download(URL)


@respx.mock
def test_non_200_is_download_error(downloader: MediaDownloader) -> None:
    respx.get(URL).respond(403)
    with pytest.raises(MediaDownloadError, match="HTTP 403"):
        downloader.download(URL)


@respx.mock
def test_timeout_is_download_error(downloader: MediaDownloader) -> None:
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(MediaDownloadError, match="timed out"):
        downloader.download(URL)


@respx.mock
def test_transport_error_is_download_error(downloader: MediaDownloader) -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(MediaDownloadError, match="ConnectError"):
        downloader.download(URL)


@respx.mock
def test_empty_body_is_download_error(downloader: MediaDownloader) -> None:
    respx.get(URL).respond(200, content=b"", headers={"content-type": "audio/mpeg"})
    with pytest.raises(MediaDownloadError, match="empty"):
        downloader.download(URL)


def test_non_http_scheme_is_rejected(downloader: MediaDownloader) -> None:
    with pytest.raises(MediaDownloadError, match="scheme"):
        downloader.download("file:///etc/passwd")
