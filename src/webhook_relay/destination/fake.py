"""In-memory CRM used in demo mode and tests."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field

from webhook_relay.schemas.domain import AttachmentRef, ContactUpsert, EngagementRecord


@dataclass
class StoredEngagement:
    """Engagement as persisted by the fake CRM."""

    id: str
    contact_id: str
    record: EngagementRecord
    attachments: list[AttachmentRef] = field(default_factory=list)


class FakeCRMDestination:
    """Dict-backed CRM with the same semantics the HTTP adapter expects from a real one."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self.contacts: dict[str, ContactUpsert] = {}
        self._contact_id_by_key: dict[str, str] = {}
        self.engagements: dict[str, StoredEngagement] = {}
        self._engagement_id_by_external: dict[str, str] = {}
        self.healthy = True

    def find_engagement(self, external_id: str) -> str | None:
        with self._lock:
            return self._engagement_id_by_external.get(external_id)

    def upsert_contact(self, contact: ContactUpsert) -> str:
        with self._lock:
            key = contact.lookup_key
            contact_id = self._contact_id_by_key.get(key)
            if contact_id is None:
                contact_id = f"contact_{next(self._ids)}"
                self._contact_id_by_key[key] = contact_id
                self.contacts[contact_id] = contact
            else:
                existing = self.contacts[contact_id]
                merged = existing.model_dump()
                merged.update({k: v for k, v in contact.model_dump().items() if v is not None})
                self.contacts[contact_id] = ContactUpsert(**merged)
            return contact_id

    def create_engagement(
        self,
        contact_id: str,
        engagement: EngagementRecord,
        attachments: list[AttachmentRef],
    ) -> str:
        with self._lock:
            if contact_id not in self.contacts:
                raise KeyError(f"unknown contact {contact_id}")
            if engagement.external_id in self._engagement_id_by_external:
                return self._engagement_id_by_external[engagement.external_id]
            engagement_id = f"engagement_{next(self._ids)}"
            self.engagements[engagement_id] = StoredEngagement(
                id=engagement_id,
                contact_id=contact_id,
                record=engagement,
                attachments=list(attachments),
            )
            self._engagement_id_by_external[engagement.external_id] = engagement_id
            return engagement_id

    def healthcheck(self) -> bool:
        return self.healthy
