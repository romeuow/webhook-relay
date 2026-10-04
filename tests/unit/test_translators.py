"""Payload -> IntegrationEvent translators."""

from __future__ import annotations

from tests.conftest import load_example_dict
from webhook_relay.idempotency.key import idempotency_key
from webhook_relay.schemas.chat import ChatMessagePayload
from webhook_relay.schemas.voice import PostCallPayload
from webhook_relay.translators.chat import ChatMessageTranslator
from webhook_relay.translators.voice import PostCallTranslator, format_transcript


def test_voice_translation_maps_contact_engagement_and_media() -> None:
    payload = PostCallPayload.model_validate(load_example_dict("payload_post_call.json"))
    event = PostCallTranslator().translate(payload)

    assert event.provider == "voice-provider"
    assert event.event_id == "evt_voice_0001"
    assert event.idempotency_key == idempotency_key("voice-provider", "evt_voice_0001")
    assert event.engagement.external_id == event.idempotency_key
    assert event.contact.phone == "+5511900000000"
    assert event.contact.name == "Ana Exemplo"
    assert event.engagement.kind == "call"
    assert event.engagement.direction == "inbound"
    assert event.engagement.duration_seconds == 270
    assert event.engagement.outcome == "connected"
    assert event.engagement.body.startswith("Cliente solicitou segunda via")
    assert "[00:04] customer: Quero a segunda via" in event.engagement.body
    assert event.engagement.properties["provider_call_id"] == "call_abc123"
    assert event.engagement.properties["meta_language"] == "pt-BR"
    assert len(event.media) == 1
    assert event.media[0].url.endswith("call_abc123.mp3")
    assert event.media[0].content_type_hint == "audio/mpeg"
    assert event.media[0].filename == "voice-provider/call_abc123/recording"


def test_voice_translation_without_recording_or_summary() -> None:
    data = load_example_dict("payload_post_call.json")
    data.pop("recording")
    data["summary"] = "   "
    data["transcript"] = []
    data["call"]["status"] = "voicemail"
    event = PostCallTranslator().translate(PostCallPayload.model_validate(data))
    assert event.media == ()
    assert event.engagement.body == ""
    assert event.engagement.outcome == "left_voicemail"


def test_translation_is_deterministic() -> None:
    payload = PostCallPayload.model_validate(load_example_dict("payload_post_call.json"))
    translator = PostCallTranslator()
    assert translator.translate(payload) == translator.translate(payload)


def test_format_transcript_renders_mm_ss() -> None:
    payload = PostCallPayload.model_validate(load_example_dict("payload_post_call.json"))
    payload.transcript[0].offset = 125.9
    lines = format_transcript(payload).splitlines()
    assert lines[0].startswith("[02:05] agent:")


def test_chat_translation_maps_message_and_attachments() -> None:
    payload = ChatMessagePayload.model_validate(load_example_dict("payload_chat_message.json"))
    event = ChatMessageTranslator().translate(payload)

    assert event.provider == "chat-provider"
    assert event.idempotency_key == idempotency_key("chat-provider", "evt_chat_0001")
    assert event.contact.phone == "+5511900000001"
    assert event.engagement.kind == "message"
    assert event.engagement.title == "whatsapp message"
    assert event.engagement.body.startswith("Boa tarde")
    assert event.engagement.properties["conversation_id"] == "conv_xyz789"
    assert len(event.media) == 1
    assert event.media[0].filename == "chat-provider/conv_xyz789/msg_001/attachment-0"
    assert event.media[0].content_type_hint == "audio/ogg"


def test_chat_translation_with_empty_text_uses_placeholder() -> None:
    data = load_example_dict("payload_chat_message.json")
    data["message"]["text"] = ""
    data["message"]["attachments"] = []
    event = ChatMessageTranslator().translate(ChatMessagePayload.model_validate(data))
    assert event.engagement.body == "(no text)"
    assert event.media == ()


def test_same_event_id_in_different_providers_yields_different_keys() -> None:
    assert idempotency_key("voice-provider", "evt_1") != idempotency_key("chat-provider", "evt_1")
