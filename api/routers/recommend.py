"""POST /api/recommend.

Wires Agent B's services into a RAGPipeline (embed -> top-k -> drop owned ->
LLM rank) and returns the results. Saving them to the user's history (TM11-64)
runs as a background task after the response is sent, so a slow or failed
write never holds up or breaks a recommendation. The query_id is made here, so
the response can carry the id the history row will be saved under, which
feedback echoes back. A pipeline failure surfaces as a structured JSON error.
When every match is a game the user owns, the body carries an `all_owned`
notice instead of a silent empty list (TM11-66).

A successful response carries each stage's time as a Server-Timing header (TM11-68),
so the browser's network tab shows where the seconds went.

The same query against the same library is answered from RESPONSE_CACHE
(TM11-73) without running the pipeline. The key includes a fingerprint of the
user's owned games, so any library change misses. A hit still gets a new
query_id and is saved to history like any other answer.
"""

from __future__ import annotations

import logging
import time
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
from api.services.rag_pipeline import RecommendOutcome
from api.services.response_cache import (
    UNCACHEABLE_NOTICES,
    ResponseCache,
    cache_key,
    log_lookup,
)

router = APIRouter(tags=["recommend"])
log = logging.getLogger("gamegpt.recommend")

# One per process (TM11-73). Tests clear it between cases.
RESPONSE_CACHE: ResponseCache[RecommendOutcome] = ResponseCache()


def _copy_of(outcome: RecommendOutcome) -> RecommendOutcome:
    """A copy whose results can be changed without touching the cached entry.

    RecommendOutcome is frozen, but its list and the Recommendations in it are
    not (PR #68 review), so both stored and served outcomes are copies.
    """
    return RecommendOutcome(
        recommendations=[r.model_copy() for r in outcome.recommendations],
        notice=outcome.notice,
    )


async def _library_fingerprint(dedup: DeduplicationService, user_id: UUID) -> str | None:
    """The cache's library key, or None to skip the cache if it can't be read."""
    try:
        return await dedup.library_fingerprint(user_id)
    except Exception:
        # A cache must never fail a recommend: answer without it.
        log.warning("recommend.cache_unavailable", exc_info=True)
        return None


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(
    req: RecommendRequest, background_tasks: BackgroundTasks, response: Response
) -> RecommendResponse:
    settings = get_settings()
    user_id = UUID(settings.dev_user_id)

    dedup = DeduplicationService()
    pipeline = RAGPipeline(
        EmbeddingService(),
        VectorStore(),
        dedup,
        LLMService(),
    )

    timings = StageTimings()
    started = time.perf_counter()
    fingerprint = await _library_fingerprint(dedup, user_id)
    lookup_ms = (time.perf_counter() - started) * 1000
    key = cache_key(user_id, req.query, fingerprint) if fingerprint is not None else None
    cached = RESPONSE_CACHE.get(key) if key is not None else None
    try:
        if cached is not None:
            outcome = _copy_of(cached)
            log_lookup(RESPONSE_CACHE, hit=True, lookup_ms=lookup_ms)
        else:
            outcome = await pipeline.recommend_outcome(user_id, req.query, timings=timings)
            store = key is not None and (
                outcome.notice is None or outcome.notice.code not in UNCACHEABLE_NOTICES
            )
            if store:
                RESPONSE_CACHE.put(key, _copy_of(outcome))
            log_lookup(RESPONSE_CACHE, hit=False, cached=store,
                       lookup_ms=lookup_ms if key is not None else None)
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
    recommendations = outcome.recommendations
    body = RecommendResponse(
        query_id=query_id,
        query=req.query,
        recommendations=recommendations,
        notice=outcome.notice,
    )
    response.headers[SERVER_TIMING_HEADER] = timings.server_timing()
    background_tasks.add_task(
        record_query,
        query_id=query_id, user_id=user_id, query=req.query, recommendations=recommendations,
    )
    return body
