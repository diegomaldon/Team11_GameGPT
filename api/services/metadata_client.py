"""MetadataClient — a reusable, rate-limited, retrying client for RAWG.

Ingestion pulls game metadata from RAWG (https://api.rawg.io/api). This client is
the one place that talks to the provider so the pull is neither *throttled* nor
*half-complete*:

- **Rate limited.** Every request (including each retry) goes through a shared
  `AsyncRateLimiter`, so a fast machine cannot burst past the provider's ceiling.
- **Retries transient failures with backoff.** 429 / 5xx / network / timeout are
  retried via tenacity with exponential backoff, honoring a `Retry-After` header
  on a 429 when the provider sends one.
- **Skips permanent failures, never aborts.** A permanent 4xx (404/401/403/…) is
  raised as `PermanentMetadataError`, which names the offending id. `fetch_many`
  logs it and keeps going, returning a `BatchResult` — the batch always finishes.

Transport-only: methods return the raw RAWG JSON. Normalization stays with the
caller (e.g. `scripts/seed_games._normalize_rawg_game`).

Following `api/services/library_sync.py`, the `httpx.AsyncClient` is injectable so
the network hop can be faked in tests (via `httpx.MockTransport`) with no key. The
`sleep`/`monotonic` are injectable too so backoff and pacing are deterministic and
instant under test.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from api.config import Settings, get_settings
from api.services.rate_limiter import AsyncRateLimiter

log = logging.getLogger("gamegpt.metadata")

_RAWG_BASE = "https://api.rawg.io/api"
_RAWG_MIN_INTERVAL = 0.25  # matches scripts/fetch_metadata.py's RAWG pacer

# Statuses worth retrying: rate limiting and transient server errors.
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


# ─────────────────────────── errors ───────────────────────────


class MetadataError(Exception):
    """Base class for every metadata-fetch failure."""


class TransientMetadataError(MetadataError):
    """A retryable failure: 429, 5xx, or a network/timeout error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after  # seconds parsed from Retry-After (429)


class PermanentMetadataError(MetadataError):
    """A non-retryable 4xx. Names the offending id so callers log + skip it.

    Never raised in a way that aborts a batch — `fetch_many` catches it, records
    it, and continues to the next id.
    """

    def __init__(self, source_id: Any, *, status_code: int, message: str = "") -> None:
        self.source_id = source_id
        self.status_code = status_code
        super().__init__(
            f"permanent error for id={source_id!r}: HTTP {status_code} {message}".rstrip()
        )


@dataclass
class BatchResult:
    """Outcome of a `fetch_many`: what landed and what was skipped."""

    successes: dict[Any, dict[str, Any]] = field(default_factory=dict)  # id -> raw JSON
    failures: list[PermanentMetadataError] = field(default_factory=list)

    @property
    def ok(self) -> int:
        return len(self.successes)

    @property
    def skipped(self) -> int:
        return len(self.failures)


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a `Retry-After` header. Numeric-seconds only; else None.

    The HTTP-date form is intentionally not handled — callers fall back to
    exponential backoff when this returns None.
    """
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


# ─────────────────────────── client ───────────────────────────


class MetadataClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        base_url: str = _RAWG_BASE,
        min_interval: float = _RAWG_MIN_INTERVAL,
        max_attempts: int = 4,
        wait_multiplier: float = 0.5,
        wait_max: float = 30.0,
        timeout: float = 20.0,
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

    # ── public API (transport-only: returns raw RAWG JSON) ──

    async def list_games(self, *, limit: int = 40, **params: Any) -> list[dict[str, Any]]:
        """List games (RAWG `/games`). Returns the `results` array."""
        query = {"page_size": min(limit, 40), **params}
        data = await self._request_json("/games", query)
        return data.get("results", []) or []

    async def fetch_game(self, rawg_id: int | str) -> dict[str, Any]:
        """Fetch one game's detail (RAWG `/games/{id}`)."""
        return await self._request_json(f"/games/{rawg_id}", {}, source_id=rawg_id)

    async def fetch_stores(self, rawg_id: int | str) -> dict[str, Any]:
        """Fetch a game's store links (RAWG `/games/{id}/stores`)."""
        return await self._request_json(
            f"/games/{rawg_id}/stores", {}, source_id=rawg_id
        )

    async def fetch_many(self, rawg_ids: Sequence[int | str]) -> BatchResult:
        """Fetch details for many ids. Skips permanent failures, never aborts."""
        result = BatchResult()
        for rawg_id in rawg_ids:
            try:
                result.successes[rawg_id] = await self.fetch_game(rawg_id)
            except PermanentMetadataError as exc:
                log.warning("metadata skip id=%s: HTTP %d", rawg_id, exc.status_code)
                result.failures.append(exc)
            except TransientMetadataError as exc:
                # Retries exhausted — treat as a skip so the batch still finishes.
                log.warning(
                    "metadata skip id=%s: transient failure persisted (HTTP %s)",
                    rawg_id,
                    exc.status_code,
                )
                result.failures.append(
                    PermanentMetadataError(
                        rawg_id,
                        status_code=exc.status_code or 0,
                        message="retries exhausted",
                    )
                )
        return result

    # ── internals ──

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
        self, path: str, params: dict[str, Any], *, source_id: Any = None
    ) -> dict[str, Any]:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait_strategy(),
            retry=retry_if_exception_type(TransientMetadataError),
            reraise=True,
            sleep=self._sleep,  # injected => no real sleep under test
        )
        async for attempt in retrying:
            with attempt:
                await self._limiter.acquire()  # pace every attempt, incl. retries
                resp = await self._send(path, params)
                return self._classify(resp, source_id).json()
        raise AssertionError("unreachable: AsyncRetrying always yields or reraises")

    async def _send(self, path: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self._base_url}{path}"
        query = dict(params)
        if self._settings.rawg_api_key:
            query.setdefault("key", self._settings.rawg_api_key)
        try:
            if self._client is not None:
                return await self._client.get(url, params=query)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                return await client.get(url, params=query)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Network-level failures are transient — let tenacity retry them.
            raise TransientMetadataError(f"network error on {url}: {exc!r}") from exc

    def _classify(self, resp: httpx.Response, source_id: Any) -> httpx.Response:
        code = resp.status_code
        if code < 400:
            return resp
        if code in _TRANSIENT_STATUS:
            raise TransientMetadataError(
                f"HTTP {code} on {resp.request.url}",
                status_code=code,
                retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
            )
        raise PermanentMetadataError(source_id, status_code=code)
