"""FastAPI application factory and ASGI entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from webhook_relay import __version__
from webhook_relay.api.health import router as health_router
from webhook_relay.api.middleware import RequestContextMiddleware
from webhook_relay.api.webhooks import router as webhooks_router
from webhook_relay.config import Settings, get_settings
from webhook_relay.container import Container, build_container
from webhook_relay.logging import configure_logging

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """Build the app. ``container`` lets tests inject fakes; otherwise it is wired from settings."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        log.info("application started", extra={"version": __version__, "app_env": settings.app_env})
        try:
            yield
        finally:
            app.state.container.close()
            log.info("application stopped")

    app = FastAPI(
        title="webhook-relay",
        version=__version__,
        summary="HMAC-authenticated webhook ingestion with idempotent delivery to a CRM.",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env == "demo" else None,
        redoc_url=None,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(webhooks_router)
    return app


app = create_app()
