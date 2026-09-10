"""POST /api/feedback.

Persists one `recommendation_feedback` row (query_id, game_id, title, rank,
vote) and returns 204. Feedback is stored only — it does not affect ranking in
the skeleton. A DB failure surfaces as a structured JSON error.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from api.db import repositories
from api.models import FeedbackRequest

router = APIRouter(tags=["feedback"])
log = logging.getLogger("gamegpt.feedback")


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(req: FeedbackRequest) -> Response:
    log.info("feedback: query_id=%s title=%s vote=%s", req.query_id, req.title, req.vote)
    try:
        await repositories.insert_feedback(req)
    except Exception as exc:
        log.exception("feedback persistence failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "db_unavailable",
                "message": "Could not persist feedback.",
            },
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
