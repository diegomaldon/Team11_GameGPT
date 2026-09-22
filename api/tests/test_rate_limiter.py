"""AsyncRateLimiter unit tests.

Deterministic and instant: a fake monotonic clock and a recording sleep stand in
for the real clock and `asyncio.sleep`, so nothing actually waits.
"""

from __future__ import annotations

import pytest

from api.services.rate_limiter import AsyncRateLimiter

pytestmark = pytest.mark.asyncio


class RecordingSleep:
    """A sleep that records requested durations instead of waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeClock:
    """A monotonic clock that only moves when the test advances it."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


async def test_first_acquire_does_not_sleep():
    sleep = RecordingSleep()
    limiter = AsyncRateLimiter(0.25, sleep=sleep, monotonic=FakeClock())
    await limiter.acquire()
    assert sleep.calls == []


async def test_second_acquire_within_window_sleeps_the_remainder():
    sleep = RecordingSleep()
    clock = FakeClock()
    limiter = AsyncRateLimiter(0.25, sleep=sleep, monotonic=clock)

    await limiter.acquire()          # no wait; sets last = now
    await limiter.acquire()          # clock unchanged => full interval remains
    assert sleep.calls == [0.25]


async def test_acquire_after_interval_elapsed_does_not_sleep():
    sleep = RecordingSleep()
    clock = FakeClock()
    limiter = AsyncRateLimiter(0.25, sleep=sleep, monotonic=clock)

    await limiter.acquire()
    clock.now += 0.5                 # more than the interval has passed
    await limiter.acquire()
    assert sleep.calls == []


async def test_partial_wait_when_some_time_has_passed():
    sleep = RecordingSleep()
    clock = FakeClock()
    limiter = AsyncRateLimiter(0.25, sleep=sleep, monotonic=clock)

    await limiter.acquire()
    clock.now += 0.10                # only part of the interval elapsed
    await limiter.acquire()
    assert sleep.calls == [pytest.approx(0.15)]


async def test_context_manager_acquires():
    sleep = RecordingSleep()
    clock = FakeClock()
    limiter = AsyncRateLimiter(0.25, sleep=sleep, monotonic=clock)

    async with limiter:
        pass
    async with limiter:              # clock unchanged => waits the interval
        pass
    assert sleep.calls == [0.25]
