"""Liveness, readiness and app wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from webhook_relay.config import Settings
from webhook_relay.container import build_container
from webhook_relay.destination.fake import FakeCRMDestination
from webhook_relay.main import create_app


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_reports_each_dependency(
    client: TestClient, destination: FakeCRMDestination
) -> None:
    ok = client.get("/readyz")
    assert ok.status_code == 200
    assert ok.json() == {
        "status": "ready",
        "checks": {"destination": True, "idempotency_store": True, "blob_storage": True},
    }
    destination.healthy = False
    degraded = client.get("/readyz")
    assert degraded.status_code == 503
    assert degraded.json()["status"] == "degraded"
    assert degraded.json()["checks"]["destination"] is False


def test_docs_disabled_outside_demo(settings: Settings) -> None:
    demo = create_app(settings)
    prod = create_app(settings.model_copy(update={"app_env": "production"}))
    assert demo.docs_url == "/docs"
    assert prod.docs_url is None


def test_default_wiring_builds_demo_container(settings: Settings) -> None:
    """Without overrides the container picks the fake/in-memory/local adapters."""
    app = create_app(settings)
    with TestClient(app) as client:
        container = app.state.container
        assert type(container.destination).__name__ == "FakeCRMDestination"
        assert type(container.idempotency_store).__name__ == "InMemoryIdempotencyStore"
        assert type(container.blob_storage).__name__ == "LocalBlobStorage"
        assert client.get("/readyz").status_code == 200


def test_container_selects_production_adapters_without_connecting(settings: Settings) -> None:
    prod = settings.model_copy(
        update={
            "crm_backend": "http",
            "idempotency_backend": "redis",
            "blob_backend": "s3",
            "s3_endpoint_url": "http://localhost:9000",
        }
    )
    container = build_container(prod)
    assert type(container.destination).__name__ == "HttpCRMDestination"
    assert type(container.idempotency_store).__name__ == "RedisIdempotencyStore"
    assert type(container.blob_storage).__name__ == "S3BlobStorage"
    container.close()
