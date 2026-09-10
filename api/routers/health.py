"""Health check — the first thing a deploy pipeline hits."""

from __future__ import annotations

from fastapi import APIRouter

from api.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "commit": get_settings().git_commit}
