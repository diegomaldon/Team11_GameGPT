"""POST /api/feedback.

PHASE 0 STUB: accepts the real body, logs it, returns 204. Agent C replaces
this body with a persisted `recommendation_feedback` row in Phase 2.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response, status

from api.models import FeedbackRequest

router = APIRouter(tags=["feedback"])
log = logging.getLogger("gamegpt.feedback")


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(req: FeedbackRequest) -> Response:
    log.info("feedback: query_id=%s title=%s vote=%s", req.query_id, req.title, req.vote)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
