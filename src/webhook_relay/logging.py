"""Structured JSON logging with request-scoped context and PII masking."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

_request_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "request_context", default=None
)


def _current() -> dict[str, Any]:
    return _request_context.get() or {}


_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
}

_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_DOCUMENT_RE = re.compile(
    r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b|\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask_phone(value: str | None) -> str | None:
    """Keep only the last four digits of a phone number: ``+55 11 90000-0000`` -> ``***0000``."""
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 4:
        return "*" * len(digits)
    return f"***{digits[-4:]}"


def mask_document(value: str | None) -> str | None:
    """Mask a national document (CPF/CNPJ-like), keeping the last two digits."""
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 2:
        return "*" * len(digits)
    return f"***{digits[-2:]}"


def mask_email(value: str | None) -> str | None:
    """Mask the local part of an e-mail address: ``ana@example.com`` -> ``a***@example.com``."""
    if not value or "@" not in value:
        return value
    local, _, domain = value.partition("@")
    return f"{local[:1]}***@{domain}"


def mask_text(value: str) -> str:
    """Best-effort masking of phones, documents and e-mails inside free text."""
    value = _EMAIL_RE.sub(lambda m: mask_email(m.group(0)) or "", value)
    value = _DOCUMENT_RE.sub(lambda m: mask_document(m.group(0)) or "", value)
    return _PHONE_RE.sub(lambda m: mask_phone(m.group(0)) or "", value)


def bind_context(**values: Any) -> None:
    """Merge values into the current request-scoped logging context."""
    current = dict(_current())
    current.update({k: v for k, v in values.items() if v is not None})
    _request_context.set(current)


def get_context() -> dict[str, Any]:
    """Return a copy of the current logging context."""
    return dict(_current())


@contextmanager
def logging_context(**values: Any) -> Iterator[None]:
    """Temporarily bind context values (restored on exit)."""
    token = _request_context.set({**_current(), **values})
    try:
        yield
    finally:
        _request_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON documents."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_text(record.getMessage()),
        }
        payload.update(_current())
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    for noisy in ("uvicorn.access", "botocore", "boto3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
