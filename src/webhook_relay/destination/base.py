"""CRMDestination protocol: the system of record for contacts and engagements."""

from __future__ import annotations

from typing import Protocol

from webhook_relay.schemas.domain import AttachmentRef, ContactUpsert, EngagementRecord


class CRMDestination(Protocol):
    """Minimal CRM surface the relay depends on."""

    def find_engagement(self, external_id: str) -> str | None:
        """Return the destination id of an engagement with ``external_id`` or ``None``."""

    def upsert_contact(self, contact: ContactUpsert) -> str:
        """Create or update a contact; return its destination id."""

    def create_engagement(
        self,
        contact_id: str,
        engagement: EngagementRecord,
        attachments: list[AttachmentRef],
    ) -> str:
        """Create the engagement linked to the contact; return its destination id."""

    def healthcheck(self) -> bool:
        """Return ``True`` when the destination is reachable."""
