"""AsyncRateLimiter — a general, reusable min-interval pacer.

Not tied to any provider: it enforces "at most one call per `min_interval`
seconds" for whatever awaits `acquire()`. Concurrent callers are serialized by
an `asyncio.Lock`, so two tasks sharing one limiter can never both slip through
inside the same window.

The clock and the sleep are injectable so a test can drive them deterministically
(a fake monotonic + a recording sleep) without any real wall-clock delay.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable


class AsyncRateLimiter:
    """Minimum-interval pacer. Cheaper than a token bucket and enough here."""

    def __init__(
        self,
        min_interval: float,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._min = min_interval
        self._sleep = sleep or asyncio.sleep
        self._mono = monotonic or time.monotonic
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Block until at least `min_interval` has elapsed since the last call."""
        async with self._lock:  # serializes concurrent callers
            gap = self._mono() - self._last
            if gap < self._min:
                await self._sleep(self._min - gap)
            self._last = self._mono()

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False
