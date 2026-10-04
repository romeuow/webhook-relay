"""Request-id propagation and request-scoped logging context."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from webhook_relay.logging import logging_context

REQUEST_ID_HEADER = "X-Request-ID"
log = logging.getLogger("webhook_relay.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Reuse the caller's ``X-Request-ID`` (or mint one) and bind it to every log line."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        with logging_context(request_id=request_id):
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            if not request.url.path.endswith(("/healthz", "/readyz")):
                log.info(
                    "request completed",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
        return response
