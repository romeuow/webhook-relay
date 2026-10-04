"""End-to-end HTTP flow with in-process fakes (TestClient)."""

from __future__ import annotations

import json

import httpx
import respx
from fastapi.testclient import TestClient

from tests.conftest import CHAT_SECRET, VOICE_RECORDING_URL, VOICE_SECRET, sign_headers
from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.storage.local import LocalBlobStorage

VOICE_PATH = "/webhooks/voice/post-call"
CHAT_PATH = "/webhooks/chat/message"


def test_voice_event_is_accepted_and_applied(
    client: TestClient,
    voice_example: bytes,
    destination: FakeCRMDestination,
    storage: LocalBlobStorage,
) -> None:
    response = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers(VOICE_SECRET, voice_example)
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["provider"] == "voice-provider"
    assert body["event_id"] == "evt_voice_0001"
    assert body["engagement_id"] in destination.engagements
    assert body["contact_id"] in destination.contacts
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["content_type"] == "audio/mpeg"
    assert (storage.root / body["attachments"][0]["key"]).exists()
    assert "media_errors" not in body
    assert response.headers["X-Request-ID"]


def test_redelivery_returns_duplicate_and_destination_has_one_record(
    client: TestClient, voice_example: bytes, destination: FakeCRMDestination
) -> None:
    headers = sign_headers(VOICE_SECRET, voice_example)
    first = client.post(VOICE_PATH, content=voice_example, headers=headers)
    second = client.post(VOICE_PATH, content=voice_example, headers=headers)
    third = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers(VOICE_SECRET, voice_example)
    )

    assert first.status_code == 202
    assert second.status_code == 200
    assert third.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["engagement_id"] == first.json()["engagement_id"]
    assert len(destination.engagements) == 1
    assert len(destination.contacts) == 1


def test_invalid_signature_returns_401_and_nothing_is_applied(
    client: TestClient, voice_example: bytes, destination: FakeCRMDestination
) -> None:
    wrong = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers("wrong", voice_example)
    )
    missing = client.post(VOICE_PATH, content=voice_example)
    expired = client.post(
        VOICE_PATH,
        content=voice_example,
        headers=sign_headers(VOICE_SECRET, voice_example, timestamp=1),
    )
    assert wrong.status_code == missing.status_code == expired.status_code == 401
    assert wrong.json() == {"detail": "invalid signature"}
    assert destination.engagements == {}


def test_tampered_body_returns_401(client: TestClient, voice_example: bytes) -> None:
    headers = sign_headers(VOICE_SECRET, voice_example)
    tampered = voice_example.replace(b"Ana Exemplo", b"Eve Exemplo")
    assert client.post(VOICE_PATH, content=tampered, headers=headers).status_code == 401


def test_invalid_payload_returns_422_without_echoing_values(
    client: TestClient, voice_example: bytes, destination: FakeCRMDestination
) -> None:
    data = json.loads(voice_example)
    data["call"]["duration_seconds"] = -1
    data["customer"]["phone"] = "+5511900000000-SECRET"
    del data["event_id"]
    body = json.dumps(data).encode()
    response = client.post(VOICE_PATH, content=body, headers=sign_headers(VOICE_SECRET, body))
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "invalid payload"
    locs = [tuple(e["loc"]) for e in payload["errors"]]
    assert ("event_id",) in locs
    assert ("call", "duration_seconds") in locs
    assert "SECRET" not in response.text
    assert destination.engagements == {}


def test_non_json_body_returns_422(client: TestClient) -> None:
    body = b"this is not json"
    response = client.post(VOICE_PATH, content=body, headers=sign_headers(VOICE_SECRET, body))
    assert response.status_code == 422


def test_oversized_body_returns_413(client: TestClient) -> None:
    body = b"{" + b" " * (1024 * 1024 + 1) + b"}"
    response = client.post(VOICE_PATH, content=body, headers=sign_headers(VOICE_SECRET, body))
    assert response.status_code == 413


def test_chat_event_uses_its_own_secret(
    client: TestClient, chat_example: bytes, destination: FakeCRMDestination
) -> None:
    cross = client.post(
        CHAT_PATH, content=chat_example, headers=sign_headers(VOICE_SECRET, chat_example)
    )
    assert cross.status_code == 401

    response = client.post(
        CHAT_PATH, content=chat_example, headers=sign_headers(CHAT_SECRET, chat_example)
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["provider"] == "chat-provider"
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["content_type"] == "audio/ogg"
    stored = destination.engagements[body["engagement_id"]]
    assert stored.record.kind == "message"


def test_expired_recording_link_still_accepts_event(
    client: TestClient, voice_example: bytes, media_router: respx.MockRouter
) -> None:
    media_router.get(VOICE_RECORDING_URL).mock(return_value=httpx.Response(404))
    response = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers(VOICE_SECRET, voice_example)
    )
    assert response.status_code == 202
    assert response.json()["attachments"] == []
    assert "HTTP 404" in response.json()["media_errors"][0]


def test_destination_unavailable_returns_503_with_retry_after(
    client: TestClient, voice_example: bytes, destination: FakeCRMDestination, monkeypatch
) -> None:
    from webhook_relay.errors import DestinationUnavailableError

    def down(*_: object, **__: object) -> str:
        raise DestinationUnavailableError("crm down")

    monkeypatch.setattr(destination, "upsert_contact", down)
    response = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers(VOICE_SECRET, voice_example)
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"

    monkeypatch.undo()
    retry = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers(VOICE_SECRET, voice_example)
    )
    assert retry.status_code == 202, "lock must be released after a failure"


def test_destination_rejection_returns_502(
    client: TestClient, voice_example: bytes, destination: FakeCRMDestination, monkeypatch
) -> None:
    from webhook_relay.errors import DestinationError

    def reject(*_: object, **__: object) -> str:
        raise DestinationError("HTTP 422")

    monkeypatch.setattr(destination, "upsert_contact", reject)
    response = client.post(
        VOICE_PATH, content=voice_example, headers=sign_headers(VOICE_SECRET, voice_example)
    )
    assert response.status_code == 502


def test_request_id_is_propagated(client: TestClient, voice_example: bytes) -> None:
    headers = {**sign_headers(VOICE_SECRET, voice_example), "X-Request-ID": "req-from-provider"}
    response = client.post(VOICE_PATH, content=voice_example, headers=headers)
    assert response.headers["X-Request-ID"] == "req-from-provider"


def test_demo_media_is_downloaded_and_stored_end_to_end(
    client: TestClient,
    voice_example: bytes,
    media_router: respx.MockRouter,
    storage: LocalBlobStorage,
) -> None:
    """Full demo path: the relay fetches the recording from its own /demo/media endpoint."""
    from webhook_relay.api.demo import synthetic_wav

    media_router.get("http://relay.example.com/demo/media/call_abc123.wav").mock(
        return_value=httpx.Response(
            200, content=synthetic_wav(), headers={"content-type": "audio/wav"}
        )
    )
    data = json.loads(voice_example)
    data["recording"]["url"] = "http://relay.example.com/demo/media/call_abc123.wav"
    data["recording"]["content_type"] = "audio/wav"
    body = json.dumps(data).encode()
    response = client.post(VOICE_PATH, content=body, headers=sign_headers(VOICE_SECRET, body))
    assert response.status_code == 202
    payload = response.json()
    assert len(payload["attachments"]) == 1
    assert payload["attachments"][0]["content_type"] == "audio/wav"
    assert payload["attachments"][0]["key"].endswith(".wav")
    stored = storage.root / payload["attachments"][0]["key"]
    assert stored.read_bytes().startswith(b"RIFF")
