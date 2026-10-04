"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from webhook_relay import __version__

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up and serving."""
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    """Readiness: every dependency answers (destination, idempotency store, blob storage)."""
    checks = request.app.state.container.readiness()
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "degraded", "checks": checks}
