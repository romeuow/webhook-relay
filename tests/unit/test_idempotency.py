"""Idempotency key and stores."""

from __future__ import annotations

from typing import Any

import pytest

from webhook_relay.idempotency.key import idempotency_key
from webhook_relay.idempotency.memory import InMemoryIdempotencyStore
from webhook_relay.idempotency.redis import KEY_PREFIX, RedisIdempotencyStore


class TestKey:
    def test_is_sha256_hex_and_stable(self) -> None:
        key = idempotency_key("voice-provider", "evt_1")
        assert len(key) == 64
        assert key == idempotency_key("Voice-Provider ", " evt_1")

    def test_separator_prevents_ambiguity(self) -> None:
        assert idempotency_key("ab", "c") != idempotency_key("a", "bc")

    @pytest.mark.parametrize(("provider", "event_id"), [("", "x"), ("x", "")])
    def test_rejects_empty_parts(self, provider: str, event_id: str) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            idempotency_key(provider, event_id)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestInMemoryStore:
    def test_acquire_is_exclusive_until_released(self) -> None:
        store = InMemoryIdempotencyStore()
        assert store.acquire("k", ttl_seconds=60)
        assert not store.acquire("k", ttl_seconds=60)
        store.release("k")
        assert store.acquire("k", ttl_seconds=60)

    def test_entries_expire(self) -> None:
        clock = FakeClock()
        store = InMemoryIdempotencyStore(clock=clock)
        assert store.acquire("k", ttl_seconds=10)
        clock.now += 9
        assert not store.acquire("k", ttl_seconds=10)
        clock.now += 1
        assert store.acquire("k", ttl_seconds=10)
        assert len(store) == 1

    def test_release_unknown_key_is_noop(self) -> None:
        store = InMemoryIdempotencyStore()
        store.release("missing")
        assert store.healthcheck()


class StubRedis:
    """Mimics ``SET NX EX`` / ``DELETE`` / ``PING`` semantics."""

    def __init__(self, *, fail_ping: bool = False) -> None:
        self.data: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail_ping = fail_ping

    def set(self, name: str, value: Any, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and name in self.data:
            return None
        self.data[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True

    def delete(self, *names: str) -> int:
        return sum(1 for n in names if self.data.pop(n, None) is not None)

    def ping(self) -> bool:
        if self.fail_ping:
            raise ConnectionError("redis down")
        return True


class TestRedisStore:
    def test_acquire_uses_set_nx_ex(self) -> None:
        redis = StubRedis()
        store = RedisIdempotencyStore(redis)
        assert store.acquire("k", ttl_seconds=30)
        assert not store.acquire("k", ttl_seconds=30)
        assert redis.ttls[KEY_PREFIX + "k"] == 30
        store.release("k")
        assert store.acquire("k", ttl_seconds=30)

    def test_healthcheck(self) -> None:
        assert RedisIdempotencyStore(StubRedis()).healthcheck()
        assert not RedisIdempotencyStore(StubRedis(fail_ping=True)).healthcheck()

    def test_from_url_builds_client_without_connecting(self) -> None:
        store = RedisIdempotencyStore.from_url("redis://localhost:1/0")
        assert isinstance(store, RedisIdempotencyStore)
