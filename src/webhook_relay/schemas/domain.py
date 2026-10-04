"""Provider-agnostic model understood by the CRM destination.

Translators map each provider payload into an :class:`IntegrationEvent`; everything
downstream (idempotency, destination, storage) only knows this model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ContactUpsert(BaseModel):
    """Contact fields to create-or-update in the CRM."""

    model_config = ConfigDict(frozen=True)

    phone: str | None = None
    email: str | None = None
    name: str | None = None
    document: str | None = None

    @property
    def lookup_key(self) -> str:
        """Primary identifier used to find the contact in the destination."""
        return self.phone or self.email or ""


class MediaRef(BaseModel):
    """Binary hosted by the provider that must be copied to our own storage."""

    model_config = ConfigDict(frozen=True)

    url: str
    content_type_hint: str | None = None
    filename: str


class AttachmentRef(BaseModel):
    """Binary already persisted in our blob storage, ready to be linked in the CRM."""

    model_config = ConfigDict(frozen=True)

    key: str
    uri: str
    content_type: str
    size_bytes: int


class EngagementRecord(BaseModel):
    """A CRM engagement (call, message...) linked to a contact."""

    model_config = ConfigDict(frozen=True)

    external_id: str
    kind: Literal["call", "message"]
    occurred_at: datetime
    direction: Literal["inbound", "outbound"]
    title: str
    body: str
    duration_seconds: int | None = None
    outcome: str | None = None
    properties: dict[str, str] = Field(default_factory=dict)


class IntegrationEvent(BaseModel):
    """Everything the pipeline needs to apply one provider event to the destination."""

    model_config = ConfigDict(frozen=True)

    provider: str
    event_id: str
    idempotency_key: str
    contact: ContactUpsert
    engagement: EngagementRecord
    media: tuple[MediaRef, ...] = ()
