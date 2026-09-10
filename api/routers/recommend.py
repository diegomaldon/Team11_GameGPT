"""POST /api/recommend.

PHASE 0 STUB: returns three hardcoded recommendations from a committed fixture
after a 1.5s delay so the frontend loading state is exercised for real.
Agent C replaces this body with a call to RAGPipeline in Phase 2.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter

from api.models import RecommendRequest, RecommendResponse

router = APIRouter(tags=["recommend"])

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "recommendations.json"


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest) -> RecommendResponse:
    await asyncio.sleep(1.5)  # make the loading state real
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return RecommendResponse(
        query_id=uuid4(),
        query=req.query,
        recommendations=data["recommendations"],
    )
