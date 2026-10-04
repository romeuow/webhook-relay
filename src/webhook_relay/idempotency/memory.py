"""In-memory idempotency store (demo/tests, single process)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class InMemoryIdempotencyStore:
    """Thread-safe dict with per-key expiry; clock is injectable for deterministic tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._expires_at: dict[str, float] = {}

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        now = self._clock()
        with self._lock:
            self._purge(now)
            if key in self._expires_at:
                return False
            self._expires_at[key] = now + ttl_seconds
            return True

    def release(self, key: str) -> None:
        with self._lock:
            self._expires_at.pop(key, None)

    def healthcheck(self) -> bool:
        return True

    def __len__(self) -> int:
        with self._lock:
            self._purge(self._clock())
            return len(self._expires_at)

    def _purge(self, now: float) -> None:
        expired = [k for k, exp in self._expires_at.items() if exp <= now]
        for key in expired:
            del self._expires_at[key]
