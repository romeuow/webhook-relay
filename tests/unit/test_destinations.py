"""Fake and HTTP CRM destinations."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.destination.http import HttpCRMDestination
from webhook_relay.destination.retry import RetryPolicy
from webhook_relay.errors import DestinationError, DestinationUnavailableError
from webhook_relay.schemas.domain import AttachmentRef, ContactUpsert, EngagementRecord

BASE = "http://crm.example.com"


def engagement(external_id: str = "ext-1") -> EngagementRecord:
    return EngagementRecord(
        external_id=external_id,
        kind="call",
        occurred_at=datetime(2026, 1, 15, 14, 27, tzinfo=UTC),
        direction="inbound",
        title="Inbound call",
        body="summary",
        duration_seconds=10,
    )


class TestFakeDestination:
    def test_upsert_merges_by_lookup_key(self) -> None:
        crm = FakeCRMDestination()
        first = crm.upsert_contact(ContactUpsert(phone="+5511900000000", name="Ana Exemplo"))
        second = crm.upsert_contact(ContactUpsert(phone="+5511900000000", email="a@example.com"))
        assert first == second
        assert crm.contacts[first].name == "Ana Exemplo"
        assert crm.contacts[first].email == "a@example.com"

    def test_engagement_lookup_and_uniqueness(self) -> None:
        crm = FakeCRMDestination()
        contact_id = crm.upsert_contact(ContactUpsert(phone="+5511900000000"))
        assert crm.find_engagement("ext-1") is None
        first = crm.create_engagement(contact_id, engagement(), [])
        again = crm.create_engagement(contact_id, engagement(), [])
        assert first == again
        assert crm.find_engagement("ext-1") == first
        assert len(crm.engagements) == 1

    def test_engagement_requires_known_contact(self) -> None:
        with pytest.raises(KeyError):
            FakeCRMDestination().create_engagement("ghost", engagement(), [])

    def test_healthcheck_toggle(self) -> None:
        crm = FakeCRMDestination()
        assert crm.healthcheck()
        crm.healthy = False
        assert not crm.healthcheck()


@pytest.fixture
def http_crm() -> HttpCRMDestination:
    policy = RetryPolicy(max_retries=2, base_delay_seconds=0, max_delay_seconds=0)
    client = httpx.Client(base_url=BASE, headers={"Authorization": "Bearer t"})
    return HttpCRMDestination(BASE, "t", retry_policy=policy, client=client)


def test_http_find_engagement(respx_mock: respx.MockRouter, http_crm: HttpCRMDestination) -> None:
    respx_mock.get(f"{BASE}/engagements", params={"external_id": "ext-1"}).respond(
        200, json={"items": [{"id": 42}]}
    )
    respx_mock.get(f"{BASE}/engagements", params={"external_id": "ext-2"}).respond(
        200, json={"items": []}
    )
    assert http_crm.find_engagement("ext-1") == "42"
    assert http_crm.find_engagement("ext-2") is None


def test_http_upsert_contact_sends_non_null_fields(
    respx_mock: respx.MockRouter, http_crm: HttpCRMDestination
) -> None:
    route = respx_mock.post(f"{BASE}/contacts:upsert").respond(200, json={"id": "c-1"})
    contact_id = http_crm.upsert_contact(ContactUpsert(phone="+5511900000000", name="Ana Exemplo"))
    assert contact_id == "c-1"
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer t"
    assert b'"email"' not in sent.content


def test_http_create_engagement_serializes_attachments(
    respx_mock: respx.MockRouter, http_crm: HttpCRMDestination
) -> None:
    route = respx_mock.post(f"{BASE}/contacts/c-1/engagements").respond(201, json={"id": "e-9"})
    ref = AttachmentRef(key="k.mp3", uri="s3://b/k.mp3", content_type="audio/mpeg", size_bytes=3)
    assert http_crm.create_engagement("c-1", engagement(), [ref]) == "e-9"
    body = route.calls.last.request.content
    assert b"s3://b/k.mp3" in body
    assert b"2026-01-15T14:27:00Z" in body


def test_http_retries_5xx_then_succeeds(
    respx_mock: respx.MockRouter, http_crm: HttpCRMDestination
) -> None:
    route = respx_mock.post(f"{BASE}/contacts:upsert")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"id": "c-2"})]
    assert http_crm.upsert_contact(ContactUpsert(phone="+5511900000000")) == "c-2"
    assert route.call_count == 2


def test_http_does_not_retry_4xx(
    respx_mock: respx.MockRouter, http_crm: HttpCRMDestination
) -> None:
    route = respx_mock.post(f"{BASE}/contacts:upsert").respond(422, json={"detail": "bad"})
    with pytest.raises(DestinationError):
        http_crm.upsert_contact(ContactUpsert(phone="+5511900000000"))
    assert route.call_count == 1


def test_http_gives_up_after_budget(
    respx_mock: respx.MockRouter, http_crm: HttpCRMDestination
) -> None:
    route = respx_mock.get(f"{BASE}/engagements").respond(500)
    with pytest.raises(DestinationUnavailableError):
        http_crm.find_engagement("ext-1")
    assert route.call_count == 3


def test_http_rejects_bad_bodies(
    respx_mock: respx.MockRouter, http_crm: HttpCRMDestination
) -> None:
    respx_mock.post(f"{BASE}/contacts:upsert").respond(200, content=b"not json")
    with pytest.raises(DestinationError, match="non-JSON"):
        http_crm.upsert_contact(ContactUpsert(phone="+5511900000000"))
    respx_mock.post(f"{BASE}/contacts:upsert").respond(200, json=[1, 2])
    with pytest.raises(DestinationError, match="unexpected JSON shape"):
        http_crm.upsert_contact(ContactUpsert(phone="+5511900000000"))
    respx_mock.post(f"{BASE}/contacts:upsert").respond(200, json={"ok": True})
    with pytest.raises(DestinationError, match="missing 'id'"):
        http_crm.upsert_contact(ContactUpsert(phone="+5511900000000"))


def test_http_healthcheck(respx_mock: respx.MockRouter, http_crm: HttpCRMDestination) -> None:
    route = respx_mock.get(f"{BASE}/health").respond(200)
    assert http_crm.healthcheck()
    route.side_effect = httpx.ConnectError("down")
    assert not http_crm.healthcheck()
    http_crm.close()


def test_http_builds_default_client() -> None:
    crm = HttpCRMDestination("http://crm.example.com/", "token", timeout_seconds=3)
    assert crm._client.base_url == httpx.URL("http://crm.example.com")
    assert crm._client.headers["Authorization"] == "Bearer token"
    crm.close()
