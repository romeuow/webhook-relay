"""Inbound payload of the fictional ``VoiceProvider`` post-call webhook."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

POST_CALL_EXAMPLE: dict = {
    "event_id": "evt_voice_0001",
    "event_type": "post_call",
    "occurred_at": "2026-01-15T14:32:10Z",
    "call": {
        "call_id": "call_abc123",
        "direction": "inbound",
        "from_number": "+5511900000000",
        "to_number": "+5511000000000",
        "started_at": "2026-01-15T14:27:40Z",
        "duration_seconds": 270,
        "status": "completed",
    },
    "customer": {
        "name": "Ana Exemplo",
        "phone": "+5511900000000",
        "email": "ana.exemplo@example.com",
        "document": "000.000.000-00",
    },
    "transcript": [
        {
            "role": "agent",
            "text": "Olá, aqui é a assistente virtual. Como posso ajudar?",
            "offset": 0.0,
        },
        {"role": "customer", "text": "Quero a segunda via da minha fatura.", "offset": 4.2},
        {"role": "agent", "text": "Claro, enviei o link por SMS.", "offset": 9.8},
    ],
    "summary": "Cliente solicitou segunda via da fatura; link enviado por SMS.",
    "recording": {
        "url": "https://cdn.voiceprovider.example.com/recordings/call_abc123.mp3",
        "content_type": "audio/mpeg",
        "expires_at": "2026-01-15T15:32:10Z",
    },
    "metadata": {"agent_id": "agent_demo", "language": "pt-BR"},
}


class CallInfo(BaseModel):
    """Core telephony attributes of the call."""

    model_config = ConfigDict(extra="ignore")

    call_id: str = Field(min_length=1, max_length=128)
    direction: Literal["inbound", "outbound"]
    from_number: str = Field(min_length=3, max_length=32)
    to_number: str = Field(min_length=3, max_length=32)
    started_at: datetime
    duration_seconds: int = Field(ge=0, le=86_400)
    status: Literal["completed", "no_answer", "busy", "failed", "voicemail"]


class CustomerInfo(BaseModel):
    """Customer identity as known by the provider (all optional but phone)."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, max_length=200)
    phone: str = Field(min_length=3, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    document: str | None = Field(default=None, max_length=32)


class TranscriptTurn(BaseModel):
    """One turn of the conversation."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["agent", "customer", "system"]
    text: str = Field(max_length=10_000)
    offset: float = Field(default=0.0, ge=0)


class RecordingInfo(BaseModel):
    """Pointer to the call recording hosted by the provider (short-lived URL)."""

    model_config = ConfigDict(extra="ignore")

    url: HttpUrl
    content_type: str | None = Field(default=None, max_length=100)
    expires_at: datetime | None = None


class PostCallPayload(BaseModel):
    """Webhook body sent by ``VoiceProvider`` when a call ends."""

    model_config = ConfigDict(extra="ignore", json_schema_extra={"examples": [POST_CALL_EXAMPLE]})

    event_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["post_call"]
    occurred_at: datetime
    call: CallInfo
    customer: CustomerInfo
    transcript: list[TranscriptTurn] = Field(default_factory=list, max_length=5_000)
    summary: str = Field(default="", max_length=20_000)
    recording: RecordingInfo | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
