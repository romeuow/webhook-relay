"""Retry policy: backoff shape and retry/no-retry decisions."""

from __future__ import annotations

import random

import httpx
import pytest

from webhook_relay.destination.retry import RetryPolicy
from webhook_relay.errors import DestinationError, DestinationUnavailableError


def make_policy(max_retries: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_retries=max_retries,
        base_delay_seconds=0.1,
        max_delay_seconds=1.0,
        rng=random.Random(42),
    )


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 599])
def test_transient_statuses_are_retryable(status: int) -> None:
    assert RetryPolicy.is_retryable_status(status)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_client_errors_are_not_retryable(status: int) -> None:
    assert not RetryPolicy.is_retryable_status(status)


def test_delay_is_bounded_and_grows_with_attempt() -> None:
    policy = make_policy()
    for attempt in range(6):
        delay = policy.compute_delay(attempt)
        assert 0 <= delay <= min(1.0, 0.1 * 2**attempt)


def test_run_returns_first_success() -> None:
    calls: list[int] = []

    def op() -> httpx.Response:
        calls.append(1)
        return httpx.Response(200)

    assert make_policy().run(op, sleep=lambda _: None).status_code == 200
    assert len(calls) == 1


def test_run_retries_on_5xx_then_succeeds() -> None:
    responses = iter([httpx.Response(503), httpx.Response(500), httpx.Response(201)])
    sleeps: list[float] = []
    result = make_policy().run(lambda: next(responses), sleep=sleeps.append)
    assert result.status_code == 201
    assert len(sleeps) == 2


def test_run_does_not_retry_on_4xx() -> None:
    calls: list[int] = []

    def op() -> httpx.Response:
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(DestinationError, match="HTTP 404"):
        make_policy().run(op, sleep=lambda _: None)
    assert len(calls) == 1


def test_run_exhausts_budget_on_persistent_failure() -> None:
    calls: list[int] = []

    def op() -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    with pytest.raises(DestinationUnavailableError, match="4 attempts"):
        make_policy(max_retries=3).run(op, sleep=lambda _: None)
    assert len(calls) == 4


def test_run_retries_transport_errors() -> None:
    attempts = iter([httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.Response(200)])

    def op() -> httpx.Response:
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    assert make_policy().run(op, sleep=lambda _: None).status_code == 200


def test_zero_retries_fails_fast() -> None:
    def op() -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(DestinationUnavailableError, match="transport error"):
        make_policy(max_retries=0).run(op, sleep=lambda _: None)
