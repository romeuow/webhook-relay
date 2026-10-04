"""Pipeline orchestration: idempotency, commit point and media failure policy."""

from __future__ import annotations

import httpx
import pytest
import respx

from tests.conftest import VOICE_RECORDING_URL, load_example_dict
from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.errors import DestinationUnavailableError, MediaDownloadError
from webhook_relay.idempotency.memory import InMemoryIdempotencyStore
from webhook_relay.pipeline import WebhookPipeline
from webhook_relay.schemas.voice import PostCallPayload
from webhook_relay.storage.download import MediaDownloader
from webhook_relay.storage.local import LocalBlobStorage
from webhook_relay.translators.voice import PostCallTranslator


@pytest.fixture
def payload() -> PostCallPayload:
    return PostCallPayload.model_validate(load_example_dict("payload_post_call.json"))


@pytest.fixture
def pipeline(
    destination: FakeCRMDestination,
    idem_store: InMemoryIdempotencyStore,
    storage: LocalBlobStorage,
    downloader: MediaDownloader,
) -> WebhookPipeline[PostCallPayload]:
    return WebhookPipeline(
        translator=PostCallTranslator(),
        destination=destination,
        idempotency_store=idem_store,
        blob_storage=storage,
        downloader=downloader,
        lock_ttl_seconds=60,
    )


def test_first_delivery_is_applied(
    pipeline: WebhookPipeline[PostCallPayload],
    payload: PostCallPayload,
    destination: FakeCRMDestination,
    storage: LocalBlobStorage,
) -> None:
    result = pipeline.process(payload)
    assert result.status == "accepted"
    assert result.engagement_id in destination.engagements
    assert len(result.attachments) == 1
    assert result.media_errors == ()
    stored = destination.engagements[result.engagement_id]
    assert stored.attachments[0].content_type == "audio/mpeg"
    assert (storage.root / stored.attachments[0].key).exists()


def test_redelivery_is_duplicate_via_lock(
    pipeline: WebhookPipeline[PostCallPayload],
    payload: PostCallPayload,
    destination: FakeCRMDestination,
) -> None:
    first = pipeline.process(payload)
    second = pipeline.process(payload)
    assert second.status == "duplicate"
    assert second.engagement_id == first.engagement_id
    assert len(destination.engagements) == 1


def test_redelivery_is_duplicate_via_destination_when_lock_expired(
    pipeline: WebhookPipeline[PostCallPayload],
    payload: PostCallPayload,
    destination: FakeCRMDestination,
    idem_store: InMemoryIdempotencyStore,
) -> None:
    first = pipeline.process(payload)
    idem_store.release(first.idempotency_key)  # simulate TTL expiry / Redis restart
    second = pipeline.process(payload)
    assert second.status == "duplicate"
    assert second.engagement_id == first.engagement_id
    assert len(destination.engagements) == 1


def test_media_failure_does_not_block_event_by_default(
    pipeline: WebhookPipeline[PostCallPayload],
    payload: PostCallPayload,
    media_router: respx.MockRouter,
    destination: FakeCRMDestination,
) -> None:
    media_router.get(VOICE_RECORDING_URL).mock(return_value=httpx.Response(410))
    result = pipeline.process(payload)
    assert result.status == "accepted"
    assert result.attachments == ()
    assert len(result.media_errors) == 1
    assert "HTTP 410" in result.media_errors[0]
    assert len(destination.engagements) == 1


def test_media_failure_can_be_made_fatal_and_releases_lock(
    destination: FakeCRMDestination,
    idem_store: InMemoryIdempotencyStore,
    storage: LocalBlobStorage,
    downloader: MediaDownloader,
    media_router: respx.MockRouter,
    payload: PostCallPayload,
) -> None:
    media_router.get(VOICE_RECORDING_URL).mock(return_value=httpx.Response(410))
    strict = WebhookPipeline(
        translator=PostCallTranslator(),
        destination=destination,
        idempotency_store=idem_store,
        blob_storage=storage,
        downloader=downloader,
        fail_on_media_error=True,
    )
    with pytest.raises(MediaDownloadError):
        strict.process(payload)
    assert destination.engagements == {}
    assert len(idem_store) == 0  # lock released -> provider retry will be processed


def test_destination_failure_releases_lock_and_propagates(
    pipeline: WebhookPipeline[PostCallPayload],
    payload: PostCallPayload,
    destination: FakeCRMDestination,
    idem_store: InMemoryIdempotencyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*_: object, **__: object) -> str:
        raise DestinationUnavailableError("crm down")

    monkeypatch.setattr(destination, "create_engagement", unavailable)
    with pytest.raises(DestinationUnavailableError):
        pipeline.process(payload)
    assert len(idem_store) == 0
    assert destination.engagements == {}

    monkeypatch.undo()
    assert pipeline.process(payload).status == "accepted"


def test_provider_property(pipeline: WebhookPipeline[PostCallPayload]) -> None:
    assert pipeline.provider == "voice-provider"
