"""HMAC-SHA256 webhook signature verification with replay protection.

Header format (same scheme popularized by Stripe-style webhooks)::

    X-Signature: t=<unix_ts>,v1=<hex(hmac_sha256(secret, f"{ts}.{raw_body}"))>

The timestamp is part of the signed message, so an attacker cannot replay an old
signature with a fresh timestamp. Comparison uses ``hmac.compare_digest`` to avoid
timing side channels. The raw body **must** be used (never a re-serialized JSON).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from webhook_relay.errors import SignatureError

DEFAULT_HEADER = "X-Signature"
SCHEME_VERSION = "v1"


class SignatureVerifier(Protocol):
    """Pluggable strategy: each provider may sign webhooks differently."""

    header_name: str

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], *, now: float | None = None
    ) -> None:
        """Raise :class:`SignatureError` when the request is not authentic."""


@dataclass(frozen=True)
class ParsedSignature:
    """Decoded ``t=...,v1=...`` header."""

    timestamp: int
    signatures: tuple[str, ...]


def parse_signature_header(value: str) -> ParsedSignature:
    """Parse ``t=<ts>,v1=<hex>[,v1=<hex>...]`` (multiple ``v1`` support secret rotation)."""
    timestamp: int | None = None
    signatures: list[str] = []
    for part in value.split(","):
        key, sep, raw = part.strip().partition("=")
        if not sep:
            raise SignatureError("malformed signature header")
        if key == "t":
            try:
                timestamp = int(raw)
            except ValueError as exc:
                raise SignatureError("malformed signature timestamp") from exc
        elif key == SCHEME_VERSION:
            signatures.append(raw.strip().lower())
    if timestamp is None or not signatures:
        raise SignatureError("signature header missing timestamp or signature")
    return ParsedSignature(timestamp=timestamp, signatures=tuple(signatures))


def compute_signature(secret: str, timestamp: int, raw_body: bytes) -> str:
    """Return ``hex(hmac_sha256(secret, f"{timestamp}." + raw_body))``."""
    message = f"{timestamp}.".encode() + raw_body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_signature_header(secret: str, raw_body: bytes, timestamp: int | None = None) -> str:
    """Build the header value a provider would send (used by the sender script and tests)."""
    ts = int(time.time()) if timestamp is None else timestamp
    return f"t={ts},{SCHEME_VERSION}={compute_signature(secret, ts, raw_body)}"


class HmacSha256Verifier:
    """Verify ``X-Signature`` headers with a shared secret and a timestamp tolerance."""

    def __init__(
        self,
        secret: str,
        *,
        tolerance_seconds: int = 300,
        header_name: str = DEFAULT_HEADER,
    ) -> None:
        if not secret:
            raise ValueError("signing secret must not be empty")
        self._secret = secret
        self._tolerance = tolerance_seconds
        self.header_name = header_name

    def verify(
        self, raw_body: bytes, headers: Mapping[str, str], *, now: float | None = None
    ) -> None:
        header_value = _get_header(headers, self.header_name)
        if header_value is None:
            raise SignatureError(f"missing {self.header_name} header")
        parsed = parse_signature_header(header_value)

        current = time.time() if now is None else now
        if abs(current - parsed.timestamp) > self._tolerance:
            raise SignatureError("signature timestamp outside tolerance window")

        expected = compute_signature(self._secret, parsed.timestamp, raw_body)
        if not any(hmac.compare_digest(expected, candidate) for candidate in parsed.signatures):
            raise SignatureError("signature mismatch")


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup that works for plain dicts and Starlette headers."""
    direct = headers.get(name)
    if direct is not None:
        return direct
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None
