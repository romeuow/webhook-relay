"""Shared fixtures: every external dependency is replaced by an in-process fake."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from webhook_relay.config import Settings
from webhook_relay.container import Container, build_container
from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.idempotency.memory import InMemoryIdempotencyStore
from webhook_relay.main import create_app
from webhook_relay.security.signature import build_signature_header
from webhook_relay.storage.download import MediaDownloader
from webhook_relay.storage.local import LocalBlobStorage

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

VOICE_SECRET = "test-voice-secret"
CHAT_SECRET = "test-chat-secret"
VOICE_RECORDING_URL = "https://cdn.voiceprovider.example.com/recordings/call_abc123.mp3"
CHAT_ATTACHMENT_URL = "https://cdn.chatprovider.example.com/media/msg_001/audio.ogg"
FAKE_MP3 = b"ID3" + b"\x00" * 509
FAKE_OGG = b"OggS" + b"\x00" * 252


def sign_headers(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    """Headers a legit provider would send."""
    return {
        "Content-Type": "application/json",
        "X-Signature": build_signature_header(secret, body, timestamp=timestamp),
    }


def load_example(name: str) -> bytes:
    return (EXAMPLES / name).read_bytes()


def load_example_dict(name: str) -> dict:
    return json.loads(load_example(name))


@pytest.fixture
def voice_example() -> bytes:
    return load_example("payload_post_call.json")


@pytest.fixture
def chat_example() -> bytes:
    return load_example("payload_chat_message.json")


@pytest.fixture
def blob_dir(tmp_path: Path) -> Path:
    return tmp_path / "blobs"


@pytest.fixture
def settings(blob_dir: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="demo",
        voice_webhook_secret=VOICE_SECRET,
        chat_webhook_secret=CHAT_SECRET,
        local_blob_dir=str(blob_dir),
        media_max_bytes=1024 * 1024,
        media_allowed_content_types="audio/mpeg,audio/ogg,audio/wav",
    )


@pytest.fixture
def media_router() -> Iterator[respx.MockRouter]:
    """Mock the provider CDNs; any un-mocked URL raises (no network ever)."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        router.get(VOICE_RECORDING_URL).mock(
            return_value=httpx.Response(
                200, content=FAKE_MP3, headers={"content-type": "audio/mpeg"}
            )
        )
        router.get(CHAT_ATTACHMENT_URL).mock(
            return_value=httpx.Response(
                200, content=FAKE_OGG, headers={"content-type": "audio/ogg"}
            )
        )
        yield router


@pytest.fixture
def destination() -> FakeCRMDestination:
    return FakeCRMDestination()


@pytest.fixture
def idem_store() -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore()


@pytest.fixture
def storage(blob_dir: Path) -> LocalBlobStorage:
    return LocalBlobStorage(blob_dir)


@pytest.fixture
def downloader(settings: Settings, media_router: respx.MockRouter) -> Iterator[MediaDownloader]:
    dl = MediaDownloader(
        max_bytes=settings.media_max_bytes,
        timeout_seconds=settings.media_timeout_seconds,
        allowed_content_types=settings.allowed_media_types,
    )
    yield dl
    dl.close()


@pytest.fixture
def container(
    settings: Settings,
    destination: FakeCRMDestination,
    idem_store: InMemoryIdempotencyStore,
    storage: LocalBlobStorage,
    downloader: MediaDownloader,
) -> Container:
    return build_container(
        settings,
        destination=destination,
        idempotency_store=idem_store,
        blob_storage=storage,
        downloader=downloader,
    )


@pytest.fixture
def client(settings: Settings, container: Container) -> Iterator[TestClient]:
    app = create_app(settings, container)
    with TestClient(app) as test_client:
        yield test_client
