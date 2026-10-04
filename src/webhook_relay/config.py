"""Application settings loaded from environment variables (12-factor style)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every value has a safe default for *demo mode* (in-memory CRM, in-memory idempotency
    store and local blob storage), so the service runs with no external credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_env: Literal["demo", "production"] = "demo"
    log_level: str = "INFO"
    host: str = "0.0.0.0"  # noqa: S104 - container-friendly default, documented
    port: int = 8000

    # Webhook signing secrets (one per provider)
    voice_webhook_secret: SecretStr = SecretStr("demo-voice-secret")
    chat_webhook_secret: SecretStr = SecretStr("demo-chat-secret")
    signature_tolerance_seconds: int = Field(default=300, ge=1, le=3600)

    # CRM destination
    crm_backend: Literal["fake", "http"] = "fake"
    crm_base_url: str = "http://localhost:9999"
    crm_api_token: SecretStr = SecretStr("demo-crm-token")
    crm_timeout_seconds: float = Field(default=10.0, gt=0)
    crm_max_retries: int = Field(default=3, ge=0, le=10)

    # Idempotency store
    idempotency_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"
    idempotency_lock_ttl_seconds: int = Field(default=600, ge=1)

    # Blob storage
    blob_backend: Literal["local", "s3"] = "local"
    local_blob_dir: str = "./var/blobs"
    s3_bucket: str = "webhook-relay-recordings"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"

    # Media download guard-rails
    media_max_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    media_timeout_seconds: float = Field(default=20.0, gt=0)
    media_allowed_content_types: str = "audio/mpeg,audio/wav,audio/x-wav,audio/ogg,audio/mp4"

    @field_validator("s3_endpoint_url", mode="before")
    @classmethod
    def _empty_endpoint_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def allowed_media_types(self) -> frozenset[str]:
        """Allowed media content types as a normalized set."""
        return frozenset(
            item.strip().lower() for item in self.media_allowed_content_types.split(",") if item
        )


def get_settings() -> Settings:
    """Build settings from the environment (kept as a function to ease test overrides)."""
    return Settings()
