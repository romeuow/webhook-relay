"""Inbound payload of the fictional ``ChatProvider`` message webhook."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

CHAT_MESSAGE_EXAMPLE: dict = {
    "event_id": "evt_chat_0001",
    "event_type": "message.received",
    "occurred_at": "2026-01-15T16:05:00Z",
    "conversation_id": "conv_xyz789",
    "channel": "whatsapp",
    "sender": {
        "name": "Bruno Exemplo",
        "phone": "+5511900000001",
        "email": "bruno.exemplo@example.com",
    },
    "message": {
        "message_id": "msg_001",
        "text": "Boa tarde, gostaria de saber o status da minha solicitação.",
        "attachments": [
            {
                "url": "https://cdn.chatprovider.example.com/media/msg_001/audio.ogg",
                "content_type": "audio/ogg",
                "filename": "voice-note.ogg",
            }
        ],
    },
}


class Sender(BaseModel):
    """Identity of the person who sent the message (at least phone or e-mail)."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    email: str | None = Field(default=None, max_length=254)

    @model_validator(mode="after")
    def _require_identifier(self) -> Sender:
        if not self.phone and not self.email:
            raise ValueError("sender must have a phone or an email")
        return self


class Attachment(BaseModel):
    """Media attached to the message, hosted by the provider."""

    model_config = ConfigDict(extra="ignore")

    url: HttpUrl
    content_type: str | None = Field(default=None, max_length=100)
    filename: str | None = Field(default=None, max_length=255)


class Message(BaseModel):
    """Message content."""

    model_config = ConfigDict(extra="ignore")

    message_id: str = Field(min_length=1, max_length=128)
    text: str = Field(default="", max_length=20_000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)


class ChatMessagePayload(BaseModel):
    """Webhook body sent by ``ChatProvider`` for every inbound message."""

    model_config = ConfigDict(
        extra="ignore", json_schema_extra={"examples": [CHAT_MESSAGE_EXAMPLE]}
    )

    event_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["message.received"]
    occurred_at: datetime
    conversation_id: str = Field(min_length=1, max_length=128)
    channel: Literal["whatsapp", "webchat", "sms", "telegram"]
    sender: Sender
    message: Message
