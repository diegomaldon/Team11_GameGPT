"""POST /api/library/csv/preview and /api/library/csv/commit (TM11-55, REQ004).

HTTP only: CsvImportService does the work. Every expected failure becomes a
structured error, so the UI can branch on `error` and show `message` as is:

  422  csv file errors (empty, too big, no "title" column, broken quoting)
       and a review that no longer matches the file
  503  anything else, logged with the cause; the message stays generic

The user is the dev user, like every other route today. Real per-user auth is
an API-wide gap tracked on its own ticket, not something this route papers over.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.config import get_settings
from api.models import CsvCommitRequest, CsvCommitResponse, CsvImportRequest, CsvPreviewResponse
from api.services.csv_import import CsvImportService, CsvReviewMismatchError
from api.services.library_csv import CsvFileError

router = APIRouter(tags=["library"])
log = logging.getLogger("gamegpt.library_csv")

CSV_FAILED_MESSAGE = "Could not read your library CSV right now. Nothing was changed."

_Result = TypeVar("_Result")


@router.post("/library/csv/preview", response_model=CsvPreviewResponse)
async def preview_csv_import(req: CsvImportRequest) -> CsvPreviewResponse:
    """Per-row match results for a CSV. Writes nothing."""
    return await _handle_errors(
        CsvImportService().preview(_user_id(), req.platform, req.csv_text)
    )


@router.post("/library/csv/commit", response_model=CsvCommitResponse)
async def commit_csv_import(req: CsvCommitRequest) -> CsvCommitResponse:
    """Re-check the CSV and add the matched rows the user kept."""
    return await _handle_errors(
        CsvImportService().commit(
            _user_id(), req.platform, req.csv_text, excluded_rows=req.excluded_rows
        )
    )


def _user_id() -> UUID:
    return UUID(get_settings().dev_user_id)


async def _handle_errors(call: Awaitable[_Result]) -> _Result:
    try:
        return await call
    except (CsvFileError, CsvReviewMismatchError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": exc.code, "message": exc.user_message},
        ) from exc
    except Exception as exc:
        log.exception("csv import failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "csv_import_failed", "message": CSV_FAILED_MESSAGE},
        ) from exc
