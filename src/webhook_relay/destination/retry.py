"""Retry policy: exponential backoff with full jitter, retry only on transient failures."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

import httpx

from webhook_relay.errors import DestinationError, DestinationUnavailableError

T = TypeVar("T")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """``max_retries`` extra attempts after the first one; delay doubles each time."""

    max_retries: int = 3
    base_delay_seconds: float = 0.2
    max_delay_seconds: float = 5.0
    rng: random.Random = field(default_factory=random.Random, compare=False, repr=False)

    @staticmethod
    def is_retryable_status(status_code: int) -> bool:
        """5xx and 429 are transient; every other 4xx is a bug on our side -> do not retry."""
        return status_code in RETRYABLE_STATUS or status_code >= 500

    def compute_delay(self, attempt: int) -> float:
        """Full-jitter backoff: ``uniform(0, min(max, base * 2**attempt))``."""
        cap = min(self.max_delay_seconds, self.base_delay_seconds * (2**attempt))
        return self.rng.uniform(0, cap)

    def run(
        self,
        operation: Callable[[], httpx.Response],
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> httpx.Response:
        """Execute ``operation`` until a non-retryable response or the retry budget is spent.

        Raises :class:`DestinationUnavailableError` when retries are exhausted and
        :class:`DestinationError` on a non-retryable 4xx.
        """
        last_error: str = "unknown"
        for attempt in range(self.max_retries + 1):
            try:
                response = operation()
            except httpx.TransportError as exc:
                last_error = f"transport error: {exc.__class__.__name__}"
            else:
                if response.is_success:
                    return response
                if not self.is_retryable_status(response.status_code):
                    raise DestinationError(
                        f"destination rejected request with HTTP {response.status_code}"
                    )
                last_error = f"HTTP {response.status_code}"
            if attempt < self.max_retries:
                sleep(self.compute_delay(attempt))
        raise DestinationUnavailableError(
            f"destination unavailable after {self.max_retries + 1} attempts ({last_error})"
        )
