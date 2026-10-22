"""POST /api/library/xbox: write an Xbox title history to the library (TM11-56, REQ014).

HTTP only: XboxImportService does the work. The caller is the web app's
POST /api/xbox/import, which signs the user in to Xbox and fetches the titles;
this route never talks to Microsoft.

  503  import_failed  the write failed and was rolled back; logged with the cause

The user is the dev user, like every other route today. Real per-user auth is
an API-wide gap tracked on its own ticket (TM11-131).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.config import get_settings
from api.models import XboxImportRequest, XboxImportResponse
from api.services.xbox_import import XboxImportService

router = APIRouter(tags=["library"])
log = logging.getLogger("gamegpt.library_xbox")

IMPORT_FAILED_MESSAGE = "Could not import the Xbox library. Your previous library is unchanged."


@router.post("/library/xbox", response_model=XboxImportResponse)
async def import_xbox_library(req: XboxImportRequest) -> XboxImportResponse:
    """Match the titles to the catalogue and upsert them as platform 'xbox'."""
    user_id = UUID(get_settings().dev_user_id)
    try:
        return await XboxImportService().import_titles(user_id, req.titles)
    except Exception as exc:
        log.exception("xbox import failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "import_failed", "message": IMPORT_FAILED_MESSAGE},
        ) from exc
