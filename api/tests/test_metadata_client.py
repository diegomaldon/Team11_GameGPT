"""MetadataClient unit tests against recorded RAWG fixtures.

Every test runs offline and instant:
- `httpx.MockTransport` serves recorded fixtures / scripted statuses, so the real
  RAWG network is never touched (and no API key is needed).
- An injected recording `sleep` makes tenacity backoff and rate-limit pacing
  record their durations instead of waiting, so retries are asserted with zero
  wall-clock delay.

The rate limiter is exercised on its own in `test_rate_limiter.py`; here the
client is built with `min_interval=0.0` so `sleep.calls` reflects *only* retry
backoff, keeping those assertions unambiguous.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from api.services.metadata_client import (
    MetadataClient,
    PermanentMetadataError,
    TransientMetadataError,
    _parse_retry_after,
)

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).parent / "fixtures" / "rawg"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class RecordingSleep:
    """A sleep that records requested durations instead of waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _client(handler, *, sleep: RecordingSleep | None = None, **kw) -> MetadataClient:
    """Build a MetadataClient whose network is a MockTransport handler.

    `min_interval=0.0` keeps the rate limiter from ever sleeping so sleep.calls
    only carries retry backoff.
    """
    sleep = sleep or RecordingSleep()
    transport = httpx.MockTransport(handler)
    kw.setdefault("min_interval", 0.0)
    return MetadataClient(
        http_client=httpx.AsyncClient(transport=transport),
        sleep=sleep,
        **kw,
    )


# ─────────────────────────── success paths ───────────────────────────


async def test_fetch_game_returns_recorded_json():
    sleep = RecordingSleep()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/games/3498")
        return httpx.Response(200, json=_load("game_3498.json"))

    client = _client(handler, sleep=sleep)
    data = await client.fetch_game(3498)

    assert data["id"] == 3498
    assert data["name"] == "Grand Theft Auto V"
    assert sleep.calls == []  # no retries, no backoff


async def test_list_games_returns_results_array():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/games")
        return httpx.Response(200, json=_load("games_list.json"))

    client = _client(handler)
    games = await client.list_games(limit=40)

    assert [g["id"] for g in games] == [3498, 4200, 5286]


# ─────────────────────────── retry / backoff ───────────────────────────


async def test_429_then_success_honors_retry_after():
    sleep = RecordingSleep()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json=_load("game_3498.json"))

    client = _client(handler, sleep=sleep)
    data = await client.fetch_game(3498)

    assert data["id"] == 3498
    assert calls["n"] == 2
    assert sleep.calls == [2.0]  # server hint, not exponential


async def test_429_then_success_uses_exponential_without_header():
    sleep = RecordingSleep()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={})  # no Retry-After
        return httpx.Response(200, json=_load("game_3498.json"))

    client = _client(handler, sleep=sleep, wait_multiplier=0.5)
    await client.fetch_game(3498)

    assert sleep.calls == [0.5]  # multiplier * 2**0


async def test_network_error_retried_then_raises_transient():
    sleep = RecordingSleep()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    client = _client(handler, sleep=sleep, max_attempts=4)
    with pytest.raises(TransientMetadataError):
        await client.fetch_game(3498)

    assert calls["n"] == 4              # initial + 3 retries
    assert len(sleep.calls) == 3        # backoff after each failure but the last


async def test_5xx_is_retried():
    sleep = RecordingSleep()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={})
        return httpx.Response(200, json=_load("game_3498.json"))

    client = _client(handler, sleep=sleep)
    data = await client.fetch_game(3498)

    assert data["id"] == 3498
    assert calls["n"] == 3
    assert len(sleep.calls) == 2


# ─────────────────────────── permanent failures ───────────────────────────


async def test_permanent_404_raises_and_names_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not found."})

    client = _client(handler)
    with pytest.raises(PermanentMetadataError) as excinfo:
        await client.fetch_game(999999)

    assert excinfo.value.source_id == 999999
    assert excinfo.value.status_code == 404


async def test_permanent_404_not_retried():
    sleep = RecordingSleep()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, json={})

    client = _client(handler, sleep=sleep)
    with pytest.raises(PermanentMetadataError):
        await client.fetch_game(999999)

    assert calls["n"] == 1       # one shot, no retries
    assert sleep.calls == []


async def test_fetch_many_skips_permanent_and_continues(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/games/3498"):
            return httpx.Response(200, json=_load("game_3498.json"))
        return httpx.Response(404, json={})

    client = _client(handler)
    with caplog.at_level(logging.WARNING, logger="gamegpt.metadata"):
        result = await client.fetch_many([3498, 999999])

    assert result.ok == 1
    assert result.skipped == 1
    assert 3498 in result.successes
    assert result.failures[0].source_id == 999999
    assert "999999" in caplog.text


async def test_fetch_many_records_exhausted_transient_as_skip():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})  # always transient, never recovers

    client = _client(handler, max_attempts=2)
    result = await client.fetch_many([3498])

    assert result.ok == 0
    assert result.skipped == 1
    assert result.failures[0].source_id == 3498
    assert result.failures[0].status_code == 503


# ─────────────────────────── helpers ───────────────────────────


async def test_parse_retry_after_numeric():
    assert _parse_retry_after("2") == 2.0
    assert _parse_retry_after("0") == 0.0


async def test_parse_retry_after_invalid_returns_none():
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("-5") is None
    assert _parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
