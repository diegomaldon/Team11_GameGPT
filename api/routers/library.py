"""GET /api/library, POST /api/library/sync, and the background sync jobs.

All endpoints delegate to LibrarySyncService, which owns the real Steam Web
API call and the seeded fallback. Failures (DB down, Steam error) surface as
structured JSON errors.

TM11-49: POST /api/library/sync/jobs starts the same sync in the background and
returns immediately; the UI polls GET /api/library/sync/jobs/{job_id} for
progress (processed / total) and per-title failures. A job that ends in
`failed` was rolled back, so the previous library is unchanged.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.config import get_settings
from api.models import (
    LibraryResponse,
    LibrarySyncJob,
    LibrarySyncRequest,
    LibrarySyncResponse,
)
from api.services import LibrarySyncService
from api.services.library_sync import SYNC_FAILED_MESSAGE, sync_jobs
from api.services.steam_client import (
    SteamError,
    SteamInvalidSteamIDError,
    SteamPermanentError,
    SteamPrivateProfileError,
    SteamTransientError,
)

router = APIRouter(tags=["library"])
log = logging.getLogger("gamegpt.library")

# TM11-46 AC-02. Each Steam failure gets its own status and stable `error` code
# so the frontend branches on the code, never on prose. `message` is written for
# a person and is safe to render verbatim — it never contains an id, a key, or a
# URL. Statuses are chosen so the client can tell "you must fix something"
# (4xx) from "try again later" (5xx):
#
#   403 — the account is visible to Steam but not to us; the user can fix it
#   422 — the id we were handed is not a steamID64; the caller must fix it
#   502 — Steam rejected us (bad key); nothing the user can do
#   503 — Steam is down or throttling after retries; try again
_STEAM_ERROR_STATUS: tuple[tuple[type[SteamError], int], ...] = (
    (SteamPrivateProfileError, status.HTTP_403_FORBIDDEN),
    (SteamInvalidSteamIDError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    (SteamPermanentError, status.HTTP_502_BAD_GATEWAY),
    (SteamTransientError, status.HTTP_503_SERVICE_UNAVAILABLE),
)


def _steam_status(exc: SteamError) -> int:
    """Map a Steam failure to its HTTP status. isinstance, so a future subclass
    inherits its parent's status instead of falling through to a 500."""
    for err_type, code in _STEAM_ERROR_STATUS:
        if isinstance(exc, err_type):
            return code
    return status.HTTP_502_BAD_GATEWAY


@router.get("/library", response_model=LibraryResponse)
async def get_library() -> LibraryResponse:
    settings = get_settings()
    service = LibrarySyncService()
    try:
        items = await service.list_owned(UUID(settings.dev_user_id))
    except Exception as exc:
        log.exception("library read failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "db_unavailable", "message": "Could not read the library."},
        ) from exc
    return LibraryResponse(items=items)


@router.post("/library/sync", response_model=LibrarySyncResponse)
async def sync_library(req: LibrarySyncRequest) -> LibrarySyncResponse:
    settings = get_settings()
    service = LibrarySyncService()
    try:
        return await service.sync(UUID(settings.dev_user_id), req.steam_id)
    except HTTPException:
        raise
    except SteamError as exc:
        # Expected, explainable outcomes — log at warning, not exception. A
        # private profile is a user setting, not a stack trace.
        log.warning("steam sync rejected: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=_steam_status(exc),
            detail={"error": exc.code, "message": exc.user_message},
        ) from exc
    except Exception as exc:
        log.exception("library sync failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "sync_failed", "message": SYNC_FAILED_MESSAGE},
        ) from exc


@router.post(
    "/library/sync/jobs",
    response_model=LibrarySyncJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_sync_job(req: LibrarySyncRequest) -> LibrarySyncJob:
    """Start a background sync, or return the one already running for this user."""
    settings = get_settings()
    return sync_jobs.start(UUID(settings.dev_user_id), req.steam_id).model_copy(deep=True)


@router.get("/library/sync/jobs/{job_id}", response_model=LibrarySyncJob)
async def get_sync_job(job_id: UUID) -> LibrarySyncJob:
    settings = get_settings()
    job = sync_jobs.get(job_id, UUID(settings.dev_user_id))
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found", "message": "No such sync job."},
        )
    return job.model_copy(deep=True)
