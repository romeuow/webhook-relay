"""JSON formatter, request context and PII masking."""

from __future__ import annotations

import json
import logging

import pytest

from webhook_relay.logging import (
    JsonFormatter,
    bind_context,
    configure_logging,
    get_context,
    logging_context,
    mask_document,
    mask_email,
    mask_phone,
    mask_text,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+55 11 90000-0000", "***0000"),
        ("11900001234", "***1234"),
        ("123", "***"),
        ("", ""),
        (None, None),
    ],
)
def test_mask_phone(raw: str | None, expected: str | None) -> None:
    assert mask_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("000.000.000-00", "***00"),
        ("00.000.000/0001-91", "***91"),
        ("1", "*"),
        (None, None),
    ],
)
def test_mask_document(raw: str | None, expected: str | None) -> None:
    assert mask_document(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ana.exemplo@example.com", "a***@example.com"),
        ("not-an-email", "not-an-email"),
        (None, None),
    ],
)
def test_mask_email(raw: str | None, expected: str | None) -> None:
    assert mask_email(raw) == expected


def test_mask_text_masks_everything_at_once() -> None:
    text = "contact ana.exemplo@example.com, phone +55 11 90000-0000, cpf 000.000.000-00"
    masked = mask_text(text)
    assert "ana.exemplo" not in masked
    assert "90000-0000" not in masked
    assert "000.000.000-00" not in masked
    assert "***0000" in masked
    assert "a***@example.com" in masked


def test_json_formatter_includes_context_and_extra() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "customer phone +5511900000000", None, None
    )
    record.event_id = "evt_1"
    with logging_context(request_id="req-1", provider="voice"):
        line = formatter.format(record)
    data = json.loads(line)
    assert data["level"] == "INFO"
    assert data["request_id"] == "req-1"
    assert data["provider"] == "voice"
    assert data["event_id"] == "evt_1"
    assert data["message"] == "customer phone ***0000"
    assert "ts" in data


def test_json_formatter_renders_exceptions() -> None:
    formatter = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", None, True)
        import sys

        record.exc_info = sys.exc_info()
    data = json.loads(formatter.format(record))
    assert "RuntimeError: boom" in data["exception"]


def test_bind_context_merges_and_logging_context_restores() -> None:
    with logging_context(request_id="r1"):
        bind_context(event_id="e1", provider=None)
        assert get_context() == {"request_id": "r1", "event_id": "e1"}
        with logging_context(provider="chat"):
            assert get_context()["provider"] == "chat"
        assert "provider" not in get_context()
    assert get_context() == {}


def test_configure_logging_installs_single_json_handler() -> None:
    configure_logging("DEBUG")
    configure_logging("INFO")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    assert root.level == logging.INFO
