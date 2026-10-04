"""Per-event processing pipeline.

Stages (the first two happen at the HTTP edge, see ``api``)::

    verify -> parse -> translate -> idempotency check -> apply -> store binaries

Commit-point rule: the engagement (the record carrying ``external_id``) is created
**last**. Media is downloaded and stored before it, so a failure anywhere leaves no
half-applied record and the provider's redelivery completes the job. Blob writes are
keyed deterministically, so re-storing the same recording overwrites (not duplicates).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from webhook_relay.destination.base import CRMDestination
from webhook_relay.errors import MediaError
from webhook_relay.idempotency.base import IdempotencyStore
from webhook_relay.logging import bind_context, mask_phone
from webhook_relay.schemas.domain import AttachmentRef, IntegrationEvent, MediaRef
from webhook_relay.storage.base import BlobStorage
from webhook_relay.storage.download import MediaDownloader
from webhook_relay.translators.base import Translator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    """Outcome returned to the HTTP layer."""

    status: Literal["accepted", "duplicate"]
    provider: str
    event_id: str
    idempotency_key: str
    engagement_id: str | None = None
    contact_id: str | None = None
    attachments: tuple[AttachmentRef, ...] = ()
    media_errors: tuple[str, ...] = field(default=())


class WebhookPipeline[PayloadT: BaseModel]:
    """Glue between a translator and the destination/storage/idempotency ports."""

    def __init__(
        self,
        *,
        translator: Translator[PayloadT],
        destination: CRMDestination,
        idempotency_store: IdempotencyStore,
        blob_storage: BlobStorage,
        downloader: MediaDownloader,
        lock_ttl_seconds: int = 600,
        fail_on_media_error: bool = False,
    ) -> None:
        self._translator = translator
        self._destination = destination
        self._idempotency = idempotency_store
        self._storage = blob_storage
        self._downloader = downloader
        self._lock_ttl = lock_ttl_seconds
        self._fail_on_media_error = fail_on_media_error

    @property
    def provider(self) -> str:
        return self._translator.provider

    def process(self, payload: PayloadT) -> PipelineResult:
        event = self._translator.translate(payload)
        bind_context(
            provider=event.provider,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key[:12],
        )

        duplicate = self._check_duplicate(event)
        if duplicate is not None:
            return duplicate

        try:
            contact_id = self._destination.upsert_contact(event.contact)
            attachments, media_errors = self._store_media(event)
            engagement_id = self._destination.create_engagement(
                contact_id, event.engagement, attachments
            )
        except Exception:
            # Release the short lock so the provider's retry is not rejected as duplicate.
            self._idempotency.release(event.idempotency_key)
            log.exception("event processing failed")
            raise

        log.info(
            "event applied",
            extra={
                "contact_id": contact_id,
                "engagement_id": engagement_id,
                "attachments": len(attachments),
                "customer_phone": mask_phone(event.contact.phone),
            },
        )
        return PipelineResult(
            status="accepted",
            provider=event.provider,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            engagement_id=engagement_id,
            contact_id=contact_id,
            attachments=tuple(attachments),
            media_errors=tuple(media_errors),
        )

    # -- internals -------------------------------------------------------------------

    def _check_duplicate(self, event: IntegrationEvent) -> PipelineResult | None:
        """Two-level check: short lock (fast path / concurrency) then destination lookup."""
        if not self._idempotency.acquire(event.idempotency_key, self._lock_ttl):
            log.info("duplicate event (idempotency lock held)")
            return self._duplicate(event, self._destination.find_engagement(event.idempotency_key))

        existing = self._destination.find_engagement(event.idempotency_key)
        if existing is not None:
            log.info("duplicate event (already in destination)", extra={"engagement_id": existing})
            return self._duplicate(event, existing)
        return None

    @staticmethod
    def _duplicate(event: IntegrationEvent, engagement_id: str | None) -> PipelineResult:
        return PipelineResult(
            status="duplicate",
            provider=event.provider,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            engagement_id=engagement_id,
        )

    def _store_media(self, event: IntegrationEvent) -> tuple[list[AttachmentRef], list[str]]:
        stored: list[AttachmentRef] = []
        errors: list[str] = []
        for media in event.media:
            try:
                stored.append(self._copy_blob(media))
            except MediaError as exc:
                if self._fail_on_media_error:
                    raise
                log.warning("media skipped", extra={"reason": str(exc), "media": media.filename})
                errors.append(f"{media.filename}: {exc}")
        return stored, errors

    def _copy_blob(self, media: MediaRef) -> AttachmentRef:
        downloaded = self._downloader.download(media.url, content_type_hint=media.content_type_hint)
        ref = self._storage.put(media.filename, downloaded.data, downloaded.content_type)
        log.info(
            "media stored",
            extra={
                "blob_key": ref.key,
                "size_bytes": ref.size_bytes,
                "content_type": ref.content_type,
            },
        )
        return ref
