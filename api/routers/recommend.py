"""POST /api/recommend.

Wires Agent B's services into a RAGPipeline (embed -> top-k -> drop owned ->
LLM rank) and returns the results. Saving them to the user's history (TM11-64)
runs as a background task after the response is sent, so a slow or failed
write never holds up or breaks a recommendation. The query_id is made here, so
the response can carry the id the history row will be saved under, which
feedback echoes back. A pipeline failure surfaces as a structured JSON error.

A successful response carries each stage's time as a Server-Timing header (TM11-68),
so the browser's network tab shows where the seconds went.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status

from api.config import get_settings
from api.models import RecommendRequest, RecommendResponse
from api.observability.stage_timings import SERVER_TIMING_HEADER, StageTimings
from api.services import (
    DeduplicationService,
    EmbeddingService,
    LLMService,
    RAGPipeline,
    VectorStore,
)
from api.services.query_history import record_query

router = APIRouter(tags=["recommend"])
log = logging.getLogger("gamegpt.recommend")


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    req: RecommendRequest, background_tasks: BackgroundTasks, response: Response
) -> RecommendResponse:
    settings = get_settings()
    user_id = UUID(settings.dev_user_id)

    pipeline = RAGPipeline(
        EmbeddingService(),
        VectorStore(),
        DeduplicationService(),
        LLMService(),
    )

    timings = StageTimings()
    try:
        recommendations = await pipeline.recommend(user_id, req.query, timings=timings)
    except Exception as exc:  # embedding / vector / dedup / LLM failure
        log.exception("recommend pipeline failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "recommendation_failed",
                "message": "Could not generate recommendations.",
            },
        ) from exc

    query_id = uuid4()
    body = RecommendResponse(
        query_id=query_id,
        query=req.query,
        recommendations=recommendations,
    )
    response.headers[SERVER_TIMING_HEADER] = timings.server_timing()
    background_tasks.add_task(
        record_query,
        query_id=query_id, user_id=user_id, query=req.query, recommendations=recommendations,
    )
    return body
