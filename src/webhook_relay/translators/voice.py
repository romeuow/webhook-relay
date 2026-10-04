"""VoiceProvider post-call -> IntegrationEvent."""

from __future__ import annotations

from webhook_relay.idempotency.key import idempotency_key
from webhook_relay.schemas.domain import ContactUpsert, EngagementRecord, IntegrationEvent, MediaRef
from webhook_relay.schemas.voice import PostCallPayload

PROVIDER = "voice-provider"

_OUTCOME_BY_STATUS = {
    "completed": "connected",
    "no_answer": "no_answer",
    "busy": "busy",
    "failed": "failed",
    "voicemail": "left_voicemail",
}


def format_transcript(payload: PostCallPayload) -> str:
    """Render the transcript as plain text (``[mm:ss] role: text``)."""
    lines = []
    for turn in payload.transcript:
        minutes, seconds = divmod(int(turn.offset), 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {turn.role}: {turn.text}")
    return "\n".join(lines)


class PostCallTranslator:
    """Translate a post-call webhook into a CRM *call* engagement plus a recording to copy."""

    provider = PROVIDER

    def translate(self, payload: PostCallPayload) -> IntegrationEvent:
        key = idempotency_key(self.provider, payload.event_id)
        contact = ContactUpsert(
            phone=payload.customer.phone,
            email=payload.customer.email,
            name=payload.customer.name,
            document=payload.customer.document,
        )
        body_parts = [payload.summary.strip()] if payload.summary.strip() else []
        transcript = format_transcript(payload)
        if transcript:
            body_parts.append("--- transcript ---\n" + transcript)
        engagement = EngagementRecord(
            external_id=key,
            kind="call",
            occurred_at=payload.call.started_at,
            direction=payload.call.direction,
            title=f"{payload.call.direction.title()} call ({payload.call.duration_seconds}s)",
            body="\n\n".join(body_parts),
            duration_seconds=payload.call.duration_seconds,
            outcome=_OUTCOME_BY_STATUS[payload.call.status],
            properties={
                "provider": self.provider,
                "provider_event_id": payload.event_id,
                "provider_call_id": payload.call.call_id,
                **{f"meta_{k}": v for k, v in sorted(payload.metadata.items())},
            },
        )
        media: tuple[MediaRef, ...] = ()
        if payload.recording is not None:
            media = (
                MediaRef(
                    url=str(payload.recording.url),
                    content_type_hint=payload.recording.content_type,
                    filename=f"{self.provider}/{payload.call.call_id}/recording",
                ),
            )
        return IntegrationEvent(
            provider=self.provider,
            event_id=payload.event_id,
            idempotency_key=key,
            contact=contact,
            engagement=engagement,
            media=media,
        )
