"""Webhook endpoints: one route per provider, same pipeline shape.

Order matters: the **raw body** is read and verified before any JSON parsing, so
a forged or tampered request never reaches the pydantic layer.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from webhook_relay.errors import DestinationError, DestinationUnavailableError, SignatureError
from webhook_relay.pipeline import PipelineResult, WebhookPipeline
from webhook_relay.schemas.chat import ChatMessagePayload
from webhook_relay.schemas.voice import PostCallPayload
from webhook_relay.security.signature import SignatureVerifier

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB: webhooks are metadata, media is fetched separately

_RESPONSES: dict[int | str, dict[str, Any]] = {
    202: {"description": "Event accepted and applied to the destination."},
    200: {"description": "Duplicate delivery; nothing changed."},
    401: {"description": "Missing, expired or invalid signature."},
    413: {"description": "Body larger than the accepted limit."},
    422: {"description": "Payload failed schema validation."},
    503: {"description": "Destination unavailable; the provider should retry later."},
}


async def _handle[PayloadT: BaseModel](
    request: Request,
    *,
    verifier: SignatureVerifier,
    schema: type[PayloadT],
    pipeline: WebhookPipeline[PayloadT],
) -> JSONResponse:
    raw_body = await request.body()
    if len(raw_body) > MAX_BODY_BYTES:
        return _error(status.HTTP_413_CONTENT_TOO_LARGE, "body too large")

    try:
        verifier.verify(raw_body, request.headers)
    except SignatureError as exc:
        log.warning("signature rejected", extra={"reason": str(exc)})
        return _error(status.HTTP_401_UNAUTHORIZED, "invalid signature")

    try:
        payload = schema.model_validate_json(raw_body)
    except ValidationError as exc:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "invalid payload", "errors": _public_errors(exc)},
        )

    try:
        result = await run_in_threadpool(pipeline.process, payload)
    except DestinationUnavailableError as exc:
        log.error("destination unavailable", extra={"reason": str(exc)})
        return _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "destination unavailable, retry later",
            headers={"Retry-After": "30"},
        )
    except DestinationError as exc:
        log.error("destination rejected event", extra={"reason": str(exc)})
        return _error(status.HTTP_502_BAD_GATEWAY, "destination rejected the event")

    return _render(result)


@router.post("/voice/post-call", status_code=status.HTTP_202_ACCEPTED, responses=_RESPONSES)
async def voice_post_call(request: Request) -> JSONResponse:
    """``VoiceProvider`` post-call event: call record + recording copied to our storage."""
    container = request.app.state.container
    return await _handle(
        request,
        verifier=container.voice_verifier,
        schema=PostCallPayload,
        pipeline=container.voice_pipeline,
    )


@router.post("/chat/message", status_code=status.HTTP_202_ACCEPTED, responses=_RESPONSES)
async def chat_message(request: Request) -> JSONResponse:
    """``ChatProvider`` inbound message: message record + attachments copied to our storage."""
    container = request.app.state.container
    return await _handle(
        request,
        verifier=container.chat_verifier,
        schema=ChatMessagePayload,
        pipeline=container.chat_pipeline,
    )


def _render(result: PipelineResult) -> JSONResponse:
    body: dict[str, Any] = {
        "status": result.status,
        "provider": result.provider,
        "event_id": result.event_id,
        "idempotency_key": result.idempotency_key,
        "engagement_id": result.engagement_id,
    }
    if result.status == "duplicate":
        return JSONResponse(status_code=status.HTTP_200_OK, content=body)
    body["contact_id"] = result.contact_id
    body["attachments"] = [a.model_dump() for a in result.attachments]
    if result.media_errors:
        body["media_errors"] = list(result.media_errors)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)


def _error(code: int, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail}, headers=headers)


def _public_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Expose only field locations and messages (never the offending input values)."""
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
