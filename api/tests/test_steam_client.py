"""SteamClient unit tests against a recorded GetOwnedGames fixture (TM11-46).

AC-04 is this file. Every test runs offline and instant:
- `httpx.MockTransport` serves the recorded fixtures, so the real Steam Web API
  is never touched and no STEAM_API_KEY is needed.
- An injected recording `sleep` makes tenacity backoff and rate-limit pacing
  record durations instead of waiting, so retries and pacing are asserted with
  zero wall-clock delay.

Tests are grouped by acceptance criterion so a failure names the AC it breaks.
The fixtures under `fixtures/steam/` were captured from the live API with
`scripts/record_steam_fixture.py`, which redacts the key before writing.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from api.config import Settings
from api.services.steam_client import (
    OwnedGame,
    SteamClient,
    SteamInvalidSteamIDError,
    SteamPermanentError,
    SteamPrivateProfileError,
    SteamTransientError,
    _coerce_minutes,
    _parse_retry_after,
    is_steamid64,
)

pytestmark = pytest.mark.asyncio

_FIXTURES = Path(__file__).parent / "fixtures" / "steam"
STEAM_ID = "76561197960287930"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class RecordingSleep:
    """A sleep that records requested durations instead of waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FakeClock:
    """A monotonic clock that advances only by what the recording sleep was asked for.

    Starts at 1000.0 like `test_rate_limiter.FakeClock`. The offset matters: the
    limiter's `_last` starts at 0.0, so a clock starting at 0 would make the very
    first acquire look overdue and sleep. Real `time.monotonic()` is always far
    from zero, so starting high is what reproduces production behaviour.
    """

    def __init__(self, sleep: RecordingSleep, start: float = 1000.0) -> None:
        self._sleep = sleep
        self._start = start

    def __call__(self) -> float:
        return self._start + sum(self._sleep.calls)


def _client(
    handler,
    *,
    sleep: RecordingSleep | None = None,
    api_key: str | None = "TEST_KEY",
    **kw,
) -> SteamClient:
    """Build a SteamClient whose network is a MockTransport handler.

    `min_interval` defaults to 0.0 so `sleep.calls` carries only retry backoff;
    the pacing tests override it explicitly.
    """
    sleep = sleep or RecordingSleep()
    kw.setdefault("min_interval", 0.0)
    return SteamClient(
        settings=Settings(steam_api_key=api_key),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        sleep=sleep,
        monotonic=FakeClock(sleep),
        **kw,
    )


def _serves(payload: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


# ───────────────── AC-01: owned appids with playtime ─────────────────


class TestAC1OwnedAppidsWithPlaytime:
    async def test_returns_every_appid_from_the_recorded_fixture(self):
        client = _client(_serves(_load("owned_games.json")))
        games = await client.get_owned_games(STEAM_ID)
        assert [g.appid for g in games] == [220, 620, 413150, 1091500, 570, 292030]

    async def test_playtime_is_carried_through_in_minutes(self):
        client = _client(_serves(_load("owned_games.json")))
        by_appid = {g.appid: g for g in await client.get_owned_games(STEAM_ID)}
        assert by_appid[220].playtime_minutes == 1337
        assert by_appid[292030].playtime_minutes == 8891
        # An owned-but-never-played game is 0 minutes, not missing and not None.
        assert by_appid[1091500].playtime_minutes == 0

    async def test_names_and_recent_playtime_are_captured(self):
        client = _client(_serves(_load("owned_games.json")))
        by_appid = {g.appid: g for g in await client.get_owned_games(STEAM_ID)}
        assert by_appid[413150].name == "Stardew Valley"
        assert by_appid[413150].playtime_2weeks_minutes == 310
        # playtime_2weeks is absent for games not played recently.
        assert by_appid[220].playtime_2weeks_minutes == 0

    async def test_playtime_hours_helper(self):
        assert OwnedGame(appid=1, playtime_minutes=5420).playtime_hours == 90.3

    async def test_free_games_included_by_default(self):
        """Dota 2 is free-to-play; excluding it would make some libraries look empty."""
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(dict(request.url.params))
            return httpx.Response(200, json=_load("owned_games.json"))

        await _client(handler).get_owned_games(STEAM_ID)
        assert seen["include_played_free_games"] == "1"
        assert seen["include_appinfo"] == "1"
        assert seen["steamid"] == STEAM_ID

    async def test_public_but_empty_library_is_not_an_error(self):
        """game_count 0 with no games key is a real, visible, empty library."""
        client = _client(_serves(_load("empty_public_library.json")))
        assert await client.get_owned_games(STEAM_ID) == []

    async def test_entries_without_a_usable_appid_are_dropped(self):
        client = _client(
            _serves({"response": {"game_count": 3, "games": [
                {"appid": 220, "playtime_forever": 10},
                {"name": "no appid at all", "playtime_forever": 5},
                {"appid": "620", "playtime_forever": 5},  # string, not int
            ]}})
        )
        assert [g.appid for g in await client.get_owned_games(STEAM_ID)] == [220]

    async def test_garbage_playtime_becomes_zero_not_a_crash(self):
        client = _client(
            _serves({"response": {"game_count": 2, "games": [
                {"appid": 1, "playtime_forever": None},
                {"appid": 2, "playtime_forever": "lots"},
            ]}})
        )
        assert [g.playtime_minutes for g in await client.get_owned_games(STEAM_ID)] == [0, 0]

    async def test_coerce_minutes_rejects_bools(self):
        """isinstance(True, int) is True in Python — a flag must not become 1 minute."""
        assert _coerce_minutes(True) == 0
        assert _coerce_minutes(False) == 0
        assert _coerce_minutes(-5) == 0
        assert _coerce_minutes(12.9) == 12


# ───────────── AC-02: private profile -> typed error the UI can explain ─────────────


class TestAC2PrivateProfile:
    async def test_private_profile_raises_typed_error(self):
        """Steam answers 200 with {"response": {}} — not a 401 or 403."""
        client = _client(_serves(_load("private_profile.json")))
        with pytest.raises(SteamPrivateProfileError) as exc:
            await client.get_owned_games(STEAM_ID)
        assert exc.value.steam_id == STEAM_ID

    async def test_error_carries_a_message_the_ui_can_show_verbatim(self):
        client = _client(_serves(_load("private_profile.json")))
        with pytest.raises(SteamPrivateProfileError) as exc:
            await client.get_owned_games(STEAM_ID)
        msg = exc.value.user_message
        assert "private" in msg.lower()
        # Actionable: it names where to go, not just what went wrong.
        assert "Privacy Settings" in msg
        assert exc.value.code == "steam_profile_private"

    async def test_private_is_distinguished_from_empty(self):
        """The whole point of AC-02: an empty library must not read as private."""
        empty = _client(_serves(_load("empty_public_library.json")))
        assert await empty.get_owned_games(STEAM_ID) == []

        private = _client(_serves(_load("private_profile.json")))
        with pytest.raises(SteamPrivateProfileError):
            await private.get_owned_games(STEAM_ID)

    async def test_missing_response_object_is_treated_as_private(self):
        for payload in ({}, {"response": None}, {"response": []}):
            client = _client(_serves(payload))
            with pytest.raises(SteamPrivateProfileError):
                await client.get_owned_games(STEAM_ID)

    async def test_private_error_is_not_retried(self):
        """It is a settled answer, not a blip — retrying wastes the rate budget."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, json={"response": {}})

        with pytest.raises(SteamPrivateProfileError):
            await _client(handler).get_owned_games(STEAM_ID)
        assert len(calls) == 1

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "7656119796028793", "notanumber", "7656119796028793x"])
    async def test_malformed_steam_id_rejected_without_a_request(self, bad):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, json=_load("owned_games.json"))

        with pytest.raises(SteamInvalidSteamIDError):
            await _client(handler).get_owned_games(bad)
        assert calls == []  # never burned a request on a known-bad id

    async def test_is_steamid64(self):
        assert is_steamid64(STEAM_ID)
        assert is_steamid64(f"  {STEAM_ID}  ")
        assert not is_steamid64(None)
        assert not is_steamid64(76561197960287930)  # int, not str


# ───────────────── AC-03: rate limits respected ─────────────────


class TestAC3RateLimits:
    async def test_successive_calls_are_paced_by_min_interval(self):
        sleep = RecordingSleep()
        client = _client(
            _serves(_load("owned_games.json")), sleep=sleep, min_interval=1.0
        )
        await client.get_owned_games(STEAM_ID)
        await client.get_owned_games(STEAM_ID)
        await client.get_owned_games(STEAM_ID)
        # First call goes straight through; each later one waits out the window.
        assert len(sleep.calls) == 2
        assert all(s == pytest.approx(1.0) for s in sleep.calls)

    async def test_default_interval_stays_under_steams_daily_ceiling(self):
        """100k calls/day is ~1.16/s sustained; the default must be at or above 1s."""
        from api.services.steam_client import _STEAM_MIN_INTERVAL

        assert _STEAM_MIN_INTERVAL >= 1.0

    async def test_429_is_retried_and_honours_retry_after(self):
        responses = [
            httpx.Response(429, headers={"Retry-After": "7"}, json={}),
            httpx.Response(200, json=_load("owned_games.json")),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        sleep = RecordingSleep()
        games = await _client(handler, sleep=sleep).get_owned_games(STEAM_ID)
        assert len(games) == 6
        assert sleep.calls == [7.0]  # server's number, not our backoff curve

    async def test_retries_are_paced_too(self):
        """A retry storm is exactly when the limiter matters most."""
        responses = [
            httpx.Response(503, json={}),
            httpx.Response(200, json=_load("owned_games.json")),
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return responses.pop(0)

        sleep = RecordingSleep()
        await _client(handler, sleep=sleep, min_interval=1.0).get_owned_games(STEAM_ID)
        # One limiter wait before the retry, plus the backoff wait itself.
        assert len(sleep.calls) >= 2

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    async def test_server_errors_are_retried_then_surface_as_transient(self, status):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={})

        sleep = RecordingSleep()
        with pytest.raises(SteamTransientError):
            await _client(handler, sleep=sleep, max_attempts=3).get_owned_games(STEAM_ID)
        assert len(sleep.calls) == 2  # 3 attempts => 2 waits

    async def test_network_errors_are_transient(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        with pytest.raises(SteamTransientError):
            await _client(handler, max_attempts=2).get_owned_games(STEAM_ID)

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    async def test_client_errors_are_permanent_and_not_retried(self, status):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(status, json={})

        with pytest.raises(SteamPermanentError) as exc:
            await _client(handler).get_owned_games(STEAM_ID)
        assert exc.value.status_code == status
        assert len(calls) == 1

    async def test_parse_retry_after(self):
        assert _parse_retry_after("7") == 7.0
        assert _parse_retry_after("  2.5 ") == 2.5
        assert _parse_retry_after("-1") is None
        assert _parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
        assert _parse_retry_after(None) is None


# ───────────────── key safety (not an AC, but a release blocker) ─────────────────


class TestApiKeyIsNeverLeaked:
    async def test_error_message_redacts_the_key(self):
        """Steam takes the key as ?key=, so any URL in an exception is a secret."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={})

        with pytest.raises(SteamPermanentError) as exc:
            await _client(handler, api_key="SUPERSECRET").get_owned_games(STEAM_ID)
        assert "SUPERSECRET" not in str(exc.value)
        assert "SUPERSECRET" not in exc.value.url
        assert "redacted" in exc.value.url

    async def test_key_is_sent_when_configured_and_omitted_when_not(self):
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.clear()
            seen.update(dict(request.url.params))
            return httpx.Response(200, json=_load("owned_games.json"))

        await _client(handler, api_key="ABC123").get_owned_games(STEAM_ID)
        assert seen["key"] == "ABC123"

        await _client(handler, api_key=None).get_owned_games(STEAM_ID)
        assert "key" not in seen

    async def test_non_json_body_is_transient_not_a_crash(self):
        """Steam serves an HTML error page under load; that is a blip, not a bug."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>Service Unavailable</html>")

        with pytest.raises(SteamTransientError):
            await _client(handler, max_attempts=2).get_owned_games(STEAM_ID)
