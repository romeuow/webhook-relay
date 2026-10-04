"""Settings parsing."""

from __future__ import annotations

import pytest

from webhook_relay.config import Settings, get_settings


def test_defaults_are_demo_friendly() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "demo"
    assert s.crm_backend == "fake"
    assert s.idempotency_backend == "memory"
    assert s.blob_backend == "local"
    assert s.s3_endpoint_url is None


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRM_BACKEND", "http")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://minio:9000")
    monkeypatch.setenv("MEDIA_ALLOWED_CONTENT_TYPES", " Audio/MPEG , audio/ogg,")
    monkeypatch.setenv("VOICE_WEBHOOK_SECRET", "s3cr3t")
    s = get_settings()
    assert s.crm_backend == "http"
    assert s.s3_endpoint_url == "http://minio:9000"
    assert s.allowed_media_types == frozenset({"audio/mpeg", "audio/ogg"})
    assert s.voice_webhook_secret.get_secret_value() == "s3cr3t"
    assert "s3cr3t" not in repr(s)


def test_empty_endpoint_url_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ENDPOINT_URL", "   ")
    assert Settings(_env_file=None).s3_endpoint_url is None  # type: ignore[call-arg]


def test_invalid_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="crm_backend"):
        Settings(_env_file=None, crm_backend="soap")  # type: ignore[call-arg, arg-type]
