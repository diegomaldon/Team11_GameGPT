"""POST /api/recommend.

Wires Agent B's services into a RAGPipeline (embed -> top-k -> drop owned ->
LLM rank), then persists the query row FIRST and its recommendations SECOND so
the returned `query_id` is the real, persisted `queries.id` that feedback echoes
back. Downstream and DB failures surface as structured JSON errors.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.config import get_settings
from api.db import repositories
from api.models import RecommendRequest, RecommendResponse
from api.services import (
    DeduplicationService,
    EmbeddingService,
    LLMService,
    RAGPipeline,
    VectorStore,
)

router = APIRouter(tags=["recommend"])
log = logging.getLogger("gamegpt.recommend")


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest) -> RecommendResponse:
    settings = get_settings()
    user_id = UUID(settings.dev_user_id)

    pipeline = RAGPipeline(
        EmbeddingService(),
        VectorStore(),
        DeduplicationService(),
        LLMService(),
    )

    try:
        recommendations = await pipeline.recommend(user_id, req.query)
    except Exception as exc:  # embedding / vector / dedup / LLM failure
        log.exception("recommend pipeline failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "recommendation_failed",
                "message": "Could not generate recommendations.",
            },
        ) from exc

    try:
        query_id = await repositories.insert_query(user_id, req.query)
        await repositories.insert_recommendations(query_id, recommendations)
    except Exception as exc:
        log.exception("recommend persistence failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "db_unavailable",
                "message": "Could not persist the query and recommendations.",
            },
        ) from exc

    return RecommendResponse(
        query_id=query_id,
        query=req.query,
        recommendations=recommendations,
    )
