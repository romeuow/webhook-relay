"""IdempotencyStore protocol.

The store is **not** the source of truth: it is a short-lived lock/cache that
(1) prevents two concurrent deliveries of the same event from racing and
(2) short-circuits recent duplicates without hitting the destination.
The authoritative duplicate check is the ``external_id`` lookup in the destination.
"""

from __future__ import annotations

from typing import Protocol


class IdempotencyStore(Protocol):
    """Lock-style store with TTL semantics (``SET NX EX``)."""

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        """Atomically claim ``key``; return ``False`` if it is already claimed."""

    def release(self, key: str) -> None:
        """Drop the claim so a redelivery can retry after a failure."""

    def healthcheck(self) -> bool:
        """Return ``True`` when the backing store is reachable."""
