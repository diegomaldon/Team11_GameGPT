"""POST /api/search: semantic similarity search over the catalogue (TM11-42, REQ011).

HTTP only: SemanticSearchService does the work. Read-only, so unlike
/api/recommend nothing is persisted and owned games are not dropped. It
returns what retrieval found, which is what a caller tuning retrieval needs.

  422  query blank or over 500 characters, k outside 1..50
  503  search_failed  embedding or database failure, logged with the cause
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from api.models import SemanticSearchRequest, SemanticSearchResponse
from api.services.semantic_search import SemanticSearchService

router = APIRouter(tags=["search"])
log = logging.getLogger("gamegpt.search")

SEARCH_FAILED_MESSAGE = "Could not search the catalogue right now."


@router.post("/search", response_model=SemanticSearchResponse)
async def semantic_search(req: SemanticSearchRequest) -> SemanticSearchResponse:
    """Catalogue games ranked by cosine similarity to the query, best first."""
    try:
        outcome = await SemanticSearchService().search(req.query, req.k)
    except Exception as exc:
        log.exception("semantic search failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "search_failed", "message": SEARCH_FAILED_MESSAGE},
        ) from exc
    return SemanticSearchResponse(
        query=req.query,
        k=req.k,
        model=outcome.model,
        results=outcome.results,
        took_ms=outcome.took_ms,
    )
