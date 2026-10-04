"""Sign and send an example webhook to a running webhook-relay instance.

Usage::

    uv run python scripts/send_test_webhook.py --provider voice
    uv run python scripts/send_test_webhook.py --provider chat --event-id evt_chat_0042
    uv run python scripts/send_test_webhook.py --provider voice --skew -900   # expired signature
    uv run python scripts/send_test_webhook.py --provider voice --tamper      # body != signature
    uv run python scripts/send_test_webhook.py --provider voice --local-media  # store a real blob

Secrets default to the demo values; override with ``--secret`` or the
``VOICE_WEBHOOK_SECRET`` / ``CHAT_WEBHOOK_SECRET`` environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from webhook_relay.security.signature import build_signature_header

ROOT = Path(__file__).resolve().parents[1]

PROVIDERS = {
    "voice": {
        "path": "/webhooks/voice/post-call",
        "example": ROOT / "examples" / "payload_post_call.json",
        "secret_env": "VOICE_WEBHOOK_SECRET",
        "default_secret": "demo-voice-secret",
    },
    "chat": {
        "path": "/webhooks/chat/message",
        "example": ROOT / "examples" / "payload_chat_message.json",
        "secret_env": "CHAT_WEBHOOK_SECRET",
        "default_secret": "demo-chat-secret",
    },
}


def build_request(args: argparse.Namespace) -> tuple[str, bytes, dict[str, str]]:
    """Return ``(url, raw_body, headers)`` for the chosen provider and options."""
    spec = PROVIDERS[args.provider]
    payload_path = Path(args.payload) if args.payload else spec["example"]
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    if args.event_id:
        payload["event_id"] = args.event_id
    elif args.random_event_id:
        payload["event_id"] = f"evt_{uuid.uuid4().hex[:12]}"

    if args.local_media:
        _point_media_to_relay(payload, args.url.rstrip("/"))

    raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    secret = args.secret or os.environ.get(spec["secret_env"]) or spec["default_secret"]
    signature = build_signature_header(secret, raw_body, timestamp=int(time.time()) + args.skew)
    if args.tamper:
        raw_body = raw_body.replace(b'"summary"', b'"summary_tampered"', 1)

    headers = {
        "Content-Type": "application/json",
        "X-Signature": signature,
        "X-Request-ID": uuid.uuid4().hex,
    }
    return args.url.rstrip("/") + spec["path"], raw_body, headers


def _point_media_to_relay(payload: dict, base_url: str) -> None:
    """Rewrite provider media URLs to the relay's demo CDN (``/demo/media/*.wav``)."""
    if payload.get("recording"):
        payload["recording"]["url"] = f"{base_url}/demo/media/{payload['call']['call_id']}.wav"
        payload["recording"]["content_type"] = "audio/wav"
    for index, attachment in enumerate(payload.get("message", {}).get("attachments", [])):
        attachment["url"] = f"{base_url}/demo/media/{payload['message']['message_id']}-{index}.wav"
        attachment["content_type"] = "audio/wav"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--provider", choices=PROVIDERS, default="voice")
    parser.add_argument("--url", default=os.environ.get("RELAY_URL", "http://localhost:8000"))
    parser.add_argument("--payload", help="path to a JSON payload (defaults to examples/)")
    parser.add_argument("--secret", help="signing secret (defaults to env or demo secret)")
    parser.add_argument("--event-id", help="override event_id (send twice to see 'duplicate')")
    parser.add_argument("--random-event-id", action="store_true", help="generate a fresh event_id")
    parser.add_argument("--skew", type=int, default=0, help="seconds added to the signed timestamp")
    parser.add_argument("--tamper", action="store_true", help="modify the body after signing")
    parser.add_argument(
        "--local-media",
        action="store_true",
        help="point recording/attachment URLs to the relay's /demo/media endpoint",
    )
    args = parser.parse_args(argv)

    url, body, headers = build_request(args)
    print(f"POST {url}\n  X-Signature: {headers['X-Signature']}")
    try:
        response = httpx.post(url, content=body, headers=headers, timeout=30)
    except httpx.HTTPError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1
    print(f"HTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except ValueError:
        print(response.text)
    return 0 if response.status_code < 400 else 2


if __name__ == "__main__":
    raise SystemExit(main())
