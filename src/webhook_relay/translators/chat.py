"""ChatProvider message -> IntegrationEvent."""

from __future__ import annotations

from webhook_relay.idempotency.key import idempotency_key
from webhook_relay.schemas.chat import ChatMessagePayload
from webhook_relay.schemas.domain import ContactUpsert, EngagementRecord, IntegrationEvent, MediaRef

PROVIDER = "chat-provider"


class ChatMessageTranslator:
    """Translate an inbound chat message into a CRM *message* engagement plus attachments."""

    provider = PROVIDER

    def translate(self, payload: ChatMessagePayload) -> IntegrationEvent:
        key = idempotency_key(self.provider, payload.event_id)
        contact = ContactUpsert(
            phone=payload.sender.phone,
            email=payload.sender.email,
            name=payload.sender.name,
        )
        text = payload.message.text.strip()
        engagement = EngagementRecord(
            external_id=key,
            kind="message",
            occurred_at=payload.occurred_at,
            direction="inbound",
            title=f"{payload.channel} message",
            body=text or "(no text)",
            properties={
                "provider": self.provider,
                "provider_event_id": payload.event_id,
                "conversation_id": payload.conversation_id,
                "channel": payload.channel,
                "message_id": payload.message.message_id,
            },
        )
        media = tuple(
            MediaRef(
                url=str(att.url),
                content_type_hint=att.content_type,
                filename=f"{self.provider}/{payload.conversation_id}/{payload.message.message_id}"
                f"/attachment-{index}",
            )
            for index, att in enumerate(payload.message.attachments)
        )
        return IntegrationEvent(
            provider=self.provider,
            event_id=payload.event_id,
            idempotency_key=key,
            contact=contact,
            engagement=engagement,
            media=media,
        )
