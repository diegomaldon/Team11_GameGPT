"""SteamClient — IPlayerService/GetOwnedGames (TM11-46, REQ010).

Pulls a user's raw Steam library: owned appids with playtime. One place talks to
Steam so the call is paced, retried, and fails in a way the UI can act on.

  AC-01  returns owned appids with playtime for a given Steam ID
  AC-02  a private profile raises a typed error the UI can explain
  AC-03  rate limits respected
  AC-04  unit tested against a recorded fixture

Why a private profile needs special handling
--------------------------------------------
Steam does not return 401 or 403 when a profile is private. It returns **HTTP
200** with an empty object:

    {"response": {}}

A public account that simply owns nothing is different, and the difference is
the only signal there is:

    {"response": {"game_count": 0}}        # public, empty library
    {"response": {}}                       # private (or no such account)

So `game_count` missing — not the status code, not an empty `games` list — is
what identifies a private profile. Treating the two as the same thing would
tell a user with a private profile that they own no games, which is the
confusing failure REQ010 exists to avoid.

Built to the same shape as `api/services/metadata_client.py`: injectable
`httpx.AsyncClient` so the network hop is faked with `httpx.MockTransport`, and
injectable `sleep`/`monotonic` so pacing and backoff are deterministic and
instant under test.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from api.config import Settings, get_settings
from api.observability.redaction import sanitize_url
from api.services.rate_limiter import AsyncRateLimiter

log = logging.getLogger("gamegpt.steam")

_STEAM_BASE = "https://api.steampowered.com"
_OWNED_GAMES_PATH = "/IPlayerService/GetOwnedGames/v1/"

# Steam's published ceiling is 100,000 calls per key per day (~1.16/s sustained).
# There is no documented per-second limit, so pace at 1 req/s and stay under it
# even if a caller loops. Overridable for tests and for batch jobs that know better.
_STEAM_MIN_INTERVAL = 1.0

# Statuses worth retrying: rate limiting and transient server errors.
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})

# A steamID64 for an individual account is 17 digits. Checking the shape locally
# turns a guaranteed-useless round trip into an immediate, specific error.
_STEAMID64_LENGTH = 17


# ─────────────────────────── errors ───────────────────────────


class SteamError(Exception):
    """Base class for every Steam library fetch failure.

    Every subclass carries two things the API layer relies on:
      `code`          a stable machine string the frontend branches on
      `user_message`  prose safe to render verbatim — never an id, key, or URL

    Defaults live here so `routers/library.py` can map any SteamError, including
    one added later, without risking an AttributeError on the response path.
    """

    code = "steam_error"
    user_message = "Could not read your Steam library. Try again shortly."


class SteamPrivateProfileError(SteamError):
    """AC-02. The profile (or its game details) is not publicly visible.

    Carries `steam_id` and a `user_message` the UI can show verbatim, so the
    frontend never has to compose copy from a status code.
    """

    code = "steam_profile_private"

    def __init__(self, steam_id: str) -> None:
        self.steam_id = steam_id
        self.user_message = (
            "This Steam profile is private. In Steam, open Profile → Edit Profile → "
            "Privacy Settings and set both 'My profile' and 'Game details' to Public, "
            "then try again."
        )
        super().__init__(f"steam profile {steam_id} is private or hidden")


class SteamInvalidSteamIDError(SteamError):
    """The supplied id is not a steamID64, so no request was made."""

    code = "steam_invalid_id"

    def __init__(self, steam_id: str) -> None:
        self.steam_id = steam_id
        self.user_message = (
            "That does not look like a Steam ID. A steamID64 is 17 digits, "
            "for example 76561197960287930."
        )
        super().__init__(f"{steam_id!r} is not a 17-digit steamID64")


class SteamTransientError(SteamError):
    """A retryable failure: 429, 5xx, or a network/timeout error."""

    code = "steam_unavailable"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.user_message = "Steam is not responding right now. Try again in a minute."


class SteamPermanentError(SteamError):
    """A non-retryable 4xx — usually a bad or unauthorized API key."""

    code = "steam_request_rejected"

    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        self.user_message = "Steam rejected the request. Check the configured API key."
        super().__init__(f"steam returned HTTP {status_code} for {url}")


# ─────────────────────────── model ───────────────────────────


@dataclass(frozen=True)
class OwnedGame:
    """One row of a Steam library. `playtime_minutes` is AC-01's payload."""

    appid: int
    playtime_minutes: int
    name: str | None = None
    playtime_2weeks_minutes: int = 0

    @property
    def playtime_hours(self) -> float:
        return round(self.playtime_minutes / 60, 1)


def _coerce_minutes(value: Any) -> int:
    """Steam sends playtime as whole minutes. Anything else counts as zero.

    A bool is rejected explicitly — `isinstance(True, int)` is True in Python,
    and a truthy flag silently becoming "1 minute played" is the kind of bug
    that survives for months.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a numeric-seconds `Retry-After`. The HTTP-date form falls back to backoff."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def is_steamid64(steam_id: object) -> bool:
    """True when `steam_id` has the shape of an individual steamID64."""
    if not isinstance(steam_id, str):
        return False
    s = steam_id.strip()
    return len(s) == _STEAMID64_LENGTH and s.isdigit()


# ─────────────────────────── client ───────────────────────────


class SteamClient:
    """Rate-limited, retrying reader for a Steam account's owned games."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        base_url: str = _STEAM_BASE,
        min_interval: float = _STEAM_MIN_INTERVAL,
        max_attempts: int = 4,
        wait_multiplier: float = 0.5,
        wait_max: float = 30.0,
        timeout: float = 15.0,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Injected client lets tests fake the network; None => real per-call client.
        self._client = http_client
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max_attempts
        self._wait_multiplier = wait_multiplier
        self._wait_max = wait_max
        self._timeout = timeout
        self._sleep = sleep or asyncio.sleep
        self._limiter = AsyncRateLimiter(min_interval, sleep=sleep, monotonic=monotonic)

    # ── public API ──

    async def get_owned_games(
        self,
        steam_id: str,
        *,
        include_free_games: bool = True,
    ) -> list[OwnedGame]:
        """AC-01. Owned appids with playtime for `steam_id`.

        Raises `SteamInvalidSteamIDError` for a malformed id (no request made),
        `SteamPrivateProfileError` for a hidden profile, `SteamPermanentError`
        for a rejected request, and `SteamTransientError` once retries are spent.

        A public account that owns nothing returns `[]` — that is not an error.
        """
        if not is_steamid64(steam_id):
            raise SteamInvalidSteamIDError(str(steam_id))
        steam_id = steam_id.strip()

        payload = await self._request_json(
            _OWNED_GAMES_PATH,
            {
                "steamid": steam_id,
                "include_appinfo": 1,
                # Free-to-play titles are owned games too; excluding them makes a
                # Dota-only library look empty.
                "include_played_free_games": 1 if include_free_games else 0,
                "format": "json",
            },
        )

        response = payload.get("response")
        # See the module docstring: a missing `game_count` is the private signal.
        # `{"response": {"game_count": 0}}` is a real, public, empty library.
        if not isinstance(response, dict) or "game_count" not in response:
            log.info("steam library hidden: steam_id=%s", steam_id)
            raise SteamPrivateProfileError(steam_id)

        games = response.get("games") or []  # absent when game_count is 0
        owned = [self._to_owned_game(g) for g in games if isinstance(g, dict)]
        owned = [g for g in owned if g is not None]
        log.info(
            "steam library: steam_id=%s game_count=%s parsed=%d",
            steam_id,
            response.get("game_count"),
            len(owned),
        )
        return owned

    # ── internals ──

    @staticmethod
    def _to_owned_game(raw: dict[str, Any]) -> OwnedGame | None:
        """Map one Steam `games[]` entry. Returns None when there is no usable appid."""
        appid = raw.get("appid")
        if isinstance(appid, bool) or not isinstance(appid, int):
            return None
        name = raw.get("name")
        return OwnedGame(
            appid=appid,
            playtime_minutes=_coerce_minutes(raw.get("playtime_forever")),
            name=name.strip() if isinstance(name, str) and name.strip() else None,
            playtime_2weeks_minutes=_coerce_minutes(raw.get("playtime_2weeks")),
        )

    def _wait_strategy(self) -> Callable[[Any], float]:
        """tenacity wait: prefer a server `Retry-After`, else exponential backoff."""
        exp = wait_exponential(multiplier=self._wait_multiplier, max=self._wait_max)

        def _wait(retry_state: Any) -> float:
            exc = retry_state.outcome.exception()
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is not None:
                return min(float(retry_after), self._wait_max)
            return exp(retry_state)

        return _wait

    async def _request_json(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait_strategy(),
            retry=retry_if_exception_type(SteamTransientError),
            reraise=True,
            sleep=self._sleep,  # injected => no real sleep under test
        )
        async for attempt in retrying:
            with attempt:
                # AC-03: pace every attempt, retries included. A retry storm is
                # exactly when a limiter matters most.
                await self._limiter.acquire()
                resp = await self._send(path, params)
                self._classify(resp)
                return self._decode(resp)
        raise AssertionError("unreachable: AsyncRetrying always yields or reraises")

    async def _send(self, path: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self._base_url}{path}"
        query = dict(params)
        if self._settings.steam_api_key:
            query.setdefault("key", self._settings.steam_api_key)
        try:
            if self._client is not None:
                return await self._client.get(url, params=query)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(url, params=query)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Network-level failures are transient — let tenacity retry them.
            # `url` here is the bare path: the key lives in `query`, which is not
            # interpolated, so this message cannot leak it.
            raise SteamTransientError(f"network error on {url}: {exc!r}") from exc

    def _classify(self, resp: httpx.Response) -> None:
        code = resp.status_code
        if code < 400:
            return
        # Never resp.raise_for_status() and never str(resp.request.url) raw:
        # Steam takes the API key as ?key=, so the URL is a secret.
        # See api/observability/upstream.py.
        safe_url = sanitize_url(str(resp.request.url))
        if code in _TRANSIENT_STATUS:
            raise SteamTransientError(
                f"HTTP {code} on {safe_url}",
                status_code=code,
                retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
            )
        raise SteamPermanentError(code, safe_url)

    @staticmethod
    def _decode(resp: httpx.Response) -> dict[str, Any]:
        """Parse the body. Steam occasionally serves HTML on an edge; treat as transient."""
        try:
            data = resp.json()
        except ValueError as exc:
            raise SteamTransientError(f"steam sent a non-JSON body: {exc}") from exc
        return data if isinstance(data, dict) else {}
