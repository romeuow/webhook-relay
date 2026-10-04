"""Translator protocol."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from webhook_relay.schemas.domain import IntegrationEvent


class Translator[PayloadT: BaseModel](Protocol):
    """Map a validated provider payload into the destination model."""

    provider: str

    def translate(self, payload: PayloadT) -> IntegrationEvent:
        """Pure function: no I/O, deterministic for the same payload."""
