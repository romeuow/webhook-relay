"""Pydantic schemas: inbound provider payloads and the internal domain model."""

from webhook_relay.schemas.chat import ChatMessagePayload
from webhook_relay.schemas.domain import (
    AttachmentRef,
    ContactUpsert,
    EngagementRecord,
    IntegrationEvent,
    MediaRef,
)
from webhook_relay.schemas.voice import PostCallPayload

__all__ = [
    "AttachmentRef",
    "ChatMessagePayload",
    "ContactUpsert",
    "EngagementRecord",
    "IntegrationEvent",
    "MediaRef",
    "PostCallPayload",
]
