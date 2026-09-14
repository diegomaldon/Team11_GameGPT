"""GET /api/library and POST /api/library/sync.

Both endpoints delegate to LibrarySyncService, which owns the real Steam Web
API call and the seeded fallback. Failures (DB down, Steam error) surface as
structured JSON errors.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.config import get_settings
from api.models import LibraryResponse, LibrarySyncRequest, LibrarySyncResponse
from api.services import LibrarySyncService

router = APIRouter(tags=["library"])
log = logging.getLogger("gamegpt.library")


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
    except Exception as exc:
        log.exception("library sync failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "sync_failed",
                "message": "Could not sync the Steam library.",
            },
        ) from exc
