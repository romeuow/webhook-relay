"""Composition root: builds concrete adapters from settings."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from webhook_relay.config import Settings
from webhook_relay.destination.base import CRMDestination
from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.destination.http import HttpCRMDestination
from webhook_relay.destination.retry import RetryPolicy
from webhook_relay.idempotency.base import IdempotencyStore
from webhook_relay.idempotency.memory import InMemoryIdempotencyStore
from webhook_relay.idempotency.redis import RedisIdempotencyStore
from webhook_relay.pipeline import WebhookPipeline
from webhook_relay.schemas.chat import ChatMessagePayload
from webhook_relay.schemas.voice import PostCallPayload
from webhook_relay.security.signature import HmacSha256Verifier, SignatureVerifier
from webhook_relay.storage.base import BlobStorage
from webhook_relay.storage.download import MediaDownloader
from webhook_relay.storage.local import LocalBlobStorage
from webhook_relay.storage.s3 import S3BlobStorage
from webhook_relay.translators.chat import ChatMessageTranslator
from webhook_relay.translators.voice import PostCallTranslator

log = logging.getLogger(__name__)


@dataclass
class Container:
    """Everything the HTTP layer needs, wired once at startup."""

    settings: Settings
    destination: CRMDestination
    idempotency_store: IdempotencyStore
    blob_storage: BlobStorage
    downloader: MediaDownloader
    voice_verifier: SignatureVerifier
    chat_verifier: SignatureVerifier
    voice_pipeline: WebhookPipeline[PostCallPayload]
    chat_pipeline: WebhookPipeline[ChatMessagePayload]

    def readiness(self) -> dict[str, bool]:
        """Probe each dependency; used by ``/readyz``."""
        return {
            "destination": self.destination.healthcheck(),
            "idempotency_store": self.idempotency_store.healthcheck(),
            "blob_storage": self.blob_storage.healthcheck(),
        }

    def close(self) -> None:
        self.downloader.close()
        close = getattr(self.destination, "close", None)
        if callable(close):
            close()


def build_destination(settings: Settings) -> CRMDestination:
    if settings.crm_backend == "http":
        return HttpCRMDestination(
            settings.crm_base_url,
            settings.crm_api_token.get_secret_value(),
            timeout_seconds=settings.crm_timeout_seconds,
            retry_policy=RetryPolicy(max_retries=settings.crm_max_retries),
        )
    return FakeCRMDestination()


def build_idempotency_store(settings: Settings) -> IdempotencyStore:
    if settings.idempotency_backend == "redis":
        return RedisIdempotencyStore.from_url(settings.redis_url)
    return InMemoryIdempotencyStore()


def build_blob_storage(settings: Settings) -> BlobStorage:
    if settings.blob_backend == "s3":
        return S3BlobStorage.from_settings(
            settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
        )
    return LocalBlobStorage(settings.local_blob_dir)


def build_container(
    settings: Settings,
    *,
    destination: CRMDestination | None = None,
    idempotency_store: IdempotencyStore | None = None,
    blob_storage: BlobStorage | None = None,
    downloader: MediaDownloader | None = None,
) -> Container:
    """Wire adapters from settings; keyword overrides let tests inject fakes."""
    destination = destination or build_destination(settings)
    idempotency_store = idempotency_store or build_idempotency_store(settings)
    blob_storage = blob_storage or build_blob_storage(settings)
    downloader = downloader or MediaDownloader(
        max_bytes=settings.media_max_bytes,
        timeout_seconds=settings.media_timeout_seconds,
        allowed_content_types=settings.allowed_media_types,
    )

    def pipeline(translator):  # type: ignore[no-untyped-def]
        return WebhookPipeline(
            translator=translator,
            destination=destination,
            idempotency_store=idempotency_store,
            blob_storage=blob_storage,
            downloader=downloader,
            lock_ttl_seconds=settings.idempotency_lock_ttl_seconds,
        )

    log.info(
        "container built",
        extra={
            "app_env": settings.app_env,
            "crm_backend": settings.crm_backend,
            "idempotency_backend": settings.idempotency_backend,
            "blob_backend": settings.blob_backend,
        },
    )
    return Container(
        settings=settings,
        destination=destination,
        idempotency_store=idempotency_store,
        blob_storage=blob_storage,
        downloader=downloader,
        voice_verifier=HmacSha256Verifier(
            settings.voice_webhook_secret.get_secret_value(),
            tolerance_seconds=settings.signature_tolerance_seconds,
        ),
        chat_verifier=HmacSha256Verifier(
            settings.chat_webhook_secret.get_secret_value(),
            tolerance_seconds=settings.signature_tolerance_seconds,
        ),
        voice_pipeline=pipeline(PostCallTranslator()),
        chat_pipeline=pipeline(ChatMessageTranslator()),
    )
