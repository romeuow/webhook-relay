"""Redis-backed idempotency store (``SET key value NX EX ttl``)."""

from __future__ import annotations

from typing import Any, Protocol

KEY_PREFIX = "webhook-relay:idem:"


class RedisLike(Protocol):
    """Minimal subset of ``redis.Redis`` used here (lets tests inject a stub)."""

    def set(self, name: str, value: Any, *, nx: bool = ..., ex: int | None = ...) -> Any: ...

    def delete(self, *names: str) -> Any: ...

    def ping(self) -> Any: ...


class RedisIdempotencyStore:
    """Multi-instance safe lock. ``SET NX EX`` is atomic, so no Lua script is needed."""

    def __init__(self, client: RedisLike, *, prefix: str = KEY_PREFIX) -> None:
        self._client = client
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> RedisIdempotencyStore:
        """Create a store backed by a real Redis connection (lazy import)."""
        import redis

        return cls(redis.Redis.from_url(url, **kwargs))

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        return bool(self._client.set(self._prefix + key, "1", nx=True, ex=ttl_seconds))

    def release(self, key: str) -> None:
        self._client.delete(self._prefix + key)

    def healthcheck(self) -> bool:
        try:
            return bool(self._client.ping())
        except Exception:
            return False
