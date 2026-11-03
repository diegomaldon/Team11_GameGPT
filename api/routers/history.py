"""GET /api/history: the user's past queries and what they returned (TM11-64, REQ037).

HTTP only: the repository reads and groups the rows. Newest first, each query
with its ranked results, titles read from the catalogue by game id.

  422  limit outside 1..50
  503  db_unavailable  the read failed, logged with the cause
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from api.config import get_settings
from api.db import repositories
from api.models import HistoryResponse
from api.models.schemas import HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT

router = APIRouter(tags=["history"])
log = logging.getLogger("gamegpt.history")

HISTORY_FAILED_MESSAGE = "Could not load your history right now."


@router.get("/history", response_model=HistoryResponse)
async def history(
    limit: int = Query(HISTORY_DEFAULT_LIMIT, ge=1, le=HISTORY_MAX_LIMIT,
                       description="How many past queries to return, newest first."),
) -> HistoryResponse:
    """The dev user's last `limit` queries with their ranked results."""
    user_id = UUID(get_settings().dev_user_id)
    try:
        entries = await repositories.list_query_history(user_id, limit=limit)
    except Exception as exc:
        log.exception("history read failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "db_unavailable", "message": HISTORY_FAILED_MESSAGE},
        ) from exc
    return HistoryResponse(items=entries)
