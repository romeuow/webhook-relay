"""HTTP CRM adapter (generic REST contract) built on httpx with retries.

The contract is intentionally generic so it can be mapped to any CRM behind a thin
proxy or adapted per vendor::

    GET  /engagements?external_id=...  -> 200 {"items": [{"id": "..."}]}
    POST /contacts:upsert              -> 200 {"id": "..."}
    POST /contacts/{id}/engagements    -> 201 {"id": "..."}
    GET  /health                       -> 200
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from webhook_relay.destination.retry import RetryPolicy
from webhook_relay.errors import DestinationError
from webhook_relay.schemas.domain import AttachmentRef, ContactUpsert, EngagementRecord

log = logging.getLogger(__name__)


class HttpCRMDestination:
    """Talks to a CRM-like REST API; retries transient failures, never retries 4xx."""

    def __init__(
        self,
        base_url: str,
        api_token: str,
        *,
        timeout_seconds: float = 10.0,
        retry_policy: RetryPolicy | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._retry = retry_policy or RetryPolicy()
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {api_token}", "User-Agent": "webhook-relay/0.1"},
        )

    def close(self) -> None:
        self._client.close()

    # -- CRMDestination ---------------------------------------------------------------

    def find_engagement(self, external_id: str) -> str | None:
        response = self._retry.run(
            lambda: self._client.get("/engagements", params={"external_id": external_id})
        )
        items = _json(response).get("items") or []
        if not items:
            return None
        return str(items[0]["id"])

    def upsert_contact(self, contact: ContactUpsert) -> str:
        body = contact.model_dump(exclude_none=True)
        response = self._retry.run(lambda: self._client.post("/contacts:upsert", json=body))
        return _extract_id(response)

    def create_engagement(
        self,
        contact_id: str,
        engagement: EngagementRecord,
        attachments: list[AttachmentRef],
    ) -> str:
        body = {
            **engagement.model_dump(mode="json", exclude_none=True),
            "attachments": [a.model_dump(mode="json") for a in attachments],
        }
        response = self._retry.run(
            lambda: self._client.post(f"/contacts/{contact_id}/engagements", json=body)
        )
        return _extract_id(response)

    def healthcheck(self) -> bool:
        try:
            return self._client.get("/health", timeout=2.0).is_success
        except httpx.HTTPError:
            return False


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise DestinationError("destination returned a non-JSON body") from exc
    if not isinstance(data, dict):
        raise DestinationError("destination returned an unexpected JSON shape")
    return data


def _extract_id(response: httpx.Response) -> str:
    data = _json(response)
    if "id" not in data:
        raise DestinationError("destination response is missing 'id'")
    return str(data["id"])
