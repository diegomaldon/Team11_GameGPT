"""LibrarySyncService — pulls a user's owned games from Steam.

SysML block: Library Sync. Real IPlayerService/GetOwnedGames call (needs only
an API key + public steamID64, no OAuth). With no STEAM_API_KEY, the
implementation falls back to seeded owned_games rows so the slice still runs.

TM11-46 moved the external call out of this module and into
`api/services/steam_client.SteamClient`, which adds playtime, rate limiting,
retries with backoff, and typed errors, including `SteamPrivateProfileError`,
which the library router turns into a message the UI can show. The client is
injectable, so the network hop can still be faked in tests without an API key.

TM11-49 (import progress + partial failure):
- `sync()` takes an optional LibrarySyncJob and advances it (state, processed,
  synced, failed) as the import runs; `SyncJobRegistry` runs that in the
  background so the UI can poll instead of staring at a frozen button.
- A bad title is reported in `failed` and the run carries on.
- The import is one transaction (repositories.import_owned_games): if the run
  itself fails, nothing is committed and the previous library is untouched.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

import httpx

from api.config import Settings, get_settings
from api.db import repositories
from api.models import (
    LibraryItem,
    LibrarySyncJob,
    LibrarySyncResponse,
    SyncFailure,
    SyncJobState,
)
from api.services.steam_client import STEAM_LIMITER, OwnedGame, SteamClient, SteamError

log = logging.getLogger("gamegpt.library_sync")

# Tiny built-in library used only when there is no Steam key AND no seed rows,
# so the dedup step and the slice still have something to chew on offline.
_FALLBACK_GAMES: list[dict[str, Any]] = [
    {"steam_appid": 620, "title": "Portal 2"},
    {"steam_appid": 292030, "title": "The Witcher 3: Wild Hunt"},
    {"steam_appid": 413150, "title": "Stardew Valley"},
    {"steam_appid": 1091500, "title": "Cyberpunk 2077"},
]

# User-facing; the cause goes to the log, never to the client (it can carry URLs/keys).
SYNC_FAILED_MESSAGE = "Could not sync the Steam library. Your previous library is unchanged."


class LibrarySyncService:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        *,
        steam_client: SteamClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Injected client lets tests fake the Steam hop; None => real network.
        self._http_client = http_client
        self._steam = steam_client or SteamClient(
            settings=self._settings, http_client=http_client, limiter=STEAM_LIMITER
        )

    async def sync(
        self, user_id: UUID, steam_id: str, job: LibrarySyncJob | None = None
    ) -> LibrarySyncResponse:
        """Fetch the Steam library for `steam_id` and upsert owned_games.

        Returns how many rows landed, which titles failed, and whether the
        source was the live Steam API ('steam') or the seeded fallback ('seed').
        If `job` is given it is updated in place as the run progresses.
        Raises if the run fails; nothing is committed in that case.
        """
        job = job or new_job()
        if self._settings.steam_api_key:
            job.state = SyncJobState.fetching
            job.source = "steam"
            # SteamPrivateProfileError / SteamInvalidSteamIDError / SteamTransientError
            # propagate on purpose: routers/library.py maps each to its own HTTP
            # status and error code so the UI can explain what happened. Swallowing
            # them here would turn "your profile is private" into "0 games synced".
            games = await self._steam.get_owned_games(steam_id)
            rows, invalid = _split_valid(games)
            await self._import(user_id, rows, invalid, job)
            log.info(
                "steam sync: user=%s steam_id=%s synced=%d failed=%d",
                user_id, steam_id, job.synced, len(job.failed),
            )
            return _finish(job)

        job.source = "seed"
        # No key: prefer whatever the DB seed (supabase/seed.sql) already holds.
        existing = await repositories.count_owned_games(user_id)
        if existing > 0:
            log.info("seed sync: user=%s reusing %d seeded rows", user_id, existing)
            job.total = job.processed = job.synced = existing
            return _finish(job)

        # No key and no seed rows: plant the built-in fallback so dedup works.
        await self._import(user_id, _FALLBACK_GAMES, [], job)
        log.info("seed sync: user=%s inserted %d fallback rows", user_id, job.synced)
        return _finish(job)

    async def list_owned(self, user_id: UUID) -> list[LibraryItem]:
        """Return the user's current owned-games library."""
        return await repositories.list_owned_games(user_id)

    async def _import(
        self,
        user_id: UUID,
        rows: list[Mapping[str, Any]],
        invalid: list[SyncFailure],
        job: LibrarySyncJob,
    ) -> None:
        job.state = SyncJobState.importing
        job.total = len(rows) + len(invalid)
        job.failed = list(invalid)
        job.processed = len(invalid)

        def on_progress(done: int, synced: int, failures: list) -> None:
            job.processed = len(invalid) + done
            job.synced = synced
            job.failed = invalid + [_failure(r, reason) for r, reason in failures]

        synced, failures = await repositories.import_owned_games(
            user_id, rows, platform="steam", on_progress=on_progress
        )
        on_progress(len(rows), synced, failures)


# ─────────────────────────── helpers ───────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_job() -> LibrarySyncJob:
    return LibrarySyncJob(job_id=uuid4(), state=SyncJobState.queued, started_at=_now())


def _failure(row: Mapping[str, Any], reason: str) -> SyncFailure:
    appid = row.get("steam_appid")
    title = row.get("title")
    return SyncFailure(
        steam_appid=appid if isinstance(appid, int) and not isinstance(appid, bool) else None,
        title=title if isinstance(title, str) else None,
        reason=reason,
    )


def _split_valid(
    games: list[OwnedGame],
) -> tuple[list[dict[str, Any]], list[SyncFailure]]:
    """Steam games -> importable rows + per-title failures. Repeated appids are dropped.

    SteamClient already drops entries without an integer appid, so what is left
    to catch here is an id Postgres would reject and a title listed twice.
    """
    rows: list[dict[str, Any]] = []
    invalid: list[SyncFailure] = []
    seen: set[int] = set()
    for g in games:
        row = {
            "steam_appid": g.appid,
            "title": g.name,
            "playtime_minutes": g.playtime_minutes,
        }
        if g.appid <= 0:
            invalid.append(_failure(row, f"invalid appid {g.appid!r}"))
            continue
        if g.appid in seen:
            continue
        seen.add(g.appid)
        rows.append(row)
    return rows, invalid


def _fail(job: LibrarySyncJob, code: str, message: str) -> None:
    job.state = SyncJobState.failed
    job.error_code = code
    job.error = message
    job.finished_at = _now()


def _finish(job: LibrarySyncJob) -> LibrarySyncResponse:
    job.state = SyncJobState.succeeded
    job.finished_at = _now()
    return LibrarySyncResponse(
        synced=job.synced,
        source=job.source or "steam",
        total=job.total,
        failed=list(job.failed),
    )


class SyncJobRegistry:
    """In-process registry of background syncs, polled via GET /api/library/sync/jobs/{id}.

    One instance per API process, so a job is only visible on the instance that
    started it. Fine for the single Render instance; a multi-instance deploy
    would move this state to the database.
    """

    def __init__(
        self,
        service_factory: Callable[[], LibrarySyncService] = LibrarySyncService,
        max_jobs: int = 200,
    ) -> None:
        self._service_factory = service_factory
        self._max_jobs = max_jobs
        self._jobs: dict[UUID, tuple[UUID, LibrarySyncJob]] = {}
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    def start(self, user_id: UUID, steam_id: str) -> LibrarySyncJob:
        """Start a sync, or return the user's sync that is already running."""
        for owner, job in self._jobs.values():
            if owner == user_id and job.finished_at is None:
                return job
        self._prune()
        job = new_job()
        self._jobs[job.job_id] = (user_id, job)
        self._tasks[job.job_id] = asyncio.create_task(self._run(user_id, steam_id, job))
        return job

    def get(self, job_id: UUID, user_id: UUID) -> LibrarySyncJob | None:
        entry = self._jobs.get(job_id)
        if entry is None or entry[0] != user_id:
            return None  # someone else's job looks exactly like no job
        return entry[1]

    async def wait(self, job_id: UUID) -> None:
        """Block until a job finishes (tests and graceful shutdown)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)

    async def _run(self, user_id: UUID, steam_id: str, job: LibrarySyncJob) -> None:
        try:
            await self._service_factory().sync(user_id, steam_id, job)
        except SteamError as exc:
            # Expected and explainable (private profile, bad id, Steam down), the
            # same cases POST /api/library/sync maps to 403/422/502/503. Keep the
            # typed message so Settings can show it. No stack trace: a user
            # setting is not a crash, and the exception text carries the steamID.
            log.warning("library sync job rejected: job=%s error=%s", job.job_id, exc.code)
            _fail(job, exc.code, exc.user_message)
        except Exception:
            log.exception("library sync job failed: job=%s", job.job_id)
            _fail(job, "sync_failed", SYNC_FAILED_MESSAGE)
        finally:
            self._tasks.pop(job.job_id, None)

    def _prune(self) -> None:
        """Forget the oldest finished jobs once the registry is full."""
        excess = len(self._jobs) - self._max_jobs + 1
        if excess <= 0:
            return
        done = [jid for jid, (_, j) in self._jobs.items() if j.finished_at is not None]
        for jid in done[:excess]:
            del self._jobs[jid]


sync_jobs = SyncJobRegistry()
