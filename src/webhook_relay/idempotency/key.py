"""Deterministic idempotency key derivation."""

from __future__ import annotations

import hashlib


def idempotency_key(provider: str, event_id: str) -> str:
    """Return ``sha256(provider + ":" + event_id)``.

    The provider prefix avoids collisions between providers that reuse id formats; the
    separator avoids ambiguity such as ``("ab", "c")`` vs ``("a", "bc")``.
    """
    if not provider or not event_id:
        raise ValueError("provider and event_id must be non-empty")
    digest = hashlib.sha256()
    digest.update(provider.strip().lower().encode("utf-8"))
    digest.update(b":")
    digest.update(event_id.strip().encode("utf-8"))
    return digest.hexdigest()
