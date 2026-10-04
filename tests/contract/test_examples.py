"""Contract tests: the shipped examples and the schema examples validate against the schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from tests.conftest import EXAMPLES
from webhook_relay.schemas.chat import CHAT_MESSAGE_EXAMPLE, ChatMessagePayload
from webhook_relay.schemas.voice import POST_CALL_EXAMPLE, PostCallPayload

CASES: list[tuple[str, type[BaseModel]]] = [
    ("payload_post_call.json", PostCallPayload),
    ("payload_chat_message.json", ChatMessagePayload),
]


@pytest.mark.parametrize(("filename", "schema"), CASES, ids=[c[0] for c in CASES])
def test_example_file_validates(filename: str, schema: type[BaseModel]) -> None:
    raw = (EXAMPLES / filename).read_bytes()
    model = schema.model_validate_json(raw)
    assert model.model_dump()["event_id"]


@pytest.mark.parametrize(("filename", "schema"), CASES, ids=[c[0] for c in CASES])
def test_example_file_matches_schema_example(filename: str, schema: type[BaseModel]) -> None:
    """examples/*.json and the OpenAPI examples must not drift apart."""
    file_data = json.loads((EXAMPLES / filename).read_text(encoding="utf-8"))
    schema_example = schema.model_json_schema()["examples"][0]
    assert schema.model_validate(file_data) == schema.model_validate(schema_example)


def test_schema_examples_are_valid() -> None:
    PostCallPayload.model_validate(POST_CALL_EXAMPLE)
    ChatMessagePayload.model_validate(CHAT_MESSAGE_EXAMPLE)


def test_examples_contain_only_synthetic_data() -> None:
    for path in EXAMPLES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "example.com" in text
        assert "Exemplo" in text
        for phone in ("+5511900000000", "+5511900000001", "+5511000000000"):
            text = text.replace(phone, "")
        assert "+55119" not in text, f"unexpected phone number in {path.name}"


def test_unknown_fields_are_ignored_not_rejected() -> None:
    data = json.loads(Path(EXAMPLES / "payload_post_call.json").read_text())
    data["future_field"] = {"nested": True}
    data["call"]["codec"] = "opus"
    PostCallPayload.model_validate(data)


@pytest.mark.parametrize(
    "mutation",
    [
        {"event_type": "call.ended"},
        {"call": {"direction": "sideways"}},
        {"recording": {"url": "not a url"}},
        {"occurred_at": "yesterday"},
    ],
)
def test_voice_schema_rejects_bad_values(mutation: dict) -> None:
    data = json.loads((EXAMPLES / "payload_post_call.json").read_text())
    for key, value in mutation.items():
        if isinstance(value, dict):
            data[key].update(value)
        else:
            data[key] = value
    with pytest.raises(ValidationError):
        PostCallPayload.model_validate(data)


def test_chat_sender_requires_phone_or_email() -> None:
    data = json.loads((EXAMPLES / "payload_chat_message.json").read_text())
    data["sender"] = {"name": "Sem Contato"}
    with pytest.raises(ValidationError, match="phone or an email"):
        ChatMessagePayload.model_validate(data)
