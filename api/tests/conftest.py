"""Shared test config for the RAG service unit tests.

Every test here runs green offline with no DB and no API keys. Tests that need
Postgres skip themselves via `has_db()`. LLM and embedding calls use the keyless
deterministic fallbacks or injected fakes — no network is touched.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from api.models import GameCandidate

# pytest-asyncio runs in strict mode by default; mark every coroutine test.
pytestmark = pytest.mark.asyncio


def make_candidate(
    title: str,
    *,
    genres: list[str] | None = None,
    tags: list[str] | None = None,
    steam_appid: int | None = None,
    review_score: float | None = None,
    similarity: float | None = None,
) -> GameCandidate:
    return GameCandidate(
        game_id=uuid4(),
        title=title,
        description=f"{title} description",
        genres=genres or [],
        tags=tags or [],
        steam_appid=steam_appid,
        review_score=review_score,
        similarity=similarity,
    )


@pytest.fixture
def candidates() -> list[GameCandidate]:
    return [
        make_candidate("Stardew Valley", genres=["Simulation", "RPG"],
                       steam_appid=413150, review_score=0.98, similarity=0.91),
        make_candidate("Coffee Talk", genres=["Visual Novel"],
                       steam_appid=914800, review_score=0.9, similarity=0.88),
        make_candidate("Dorfromantik", tags=["relaxing", "puzzle"],
                       steam_appid=1455840, review_score=0.95, similarity=0.85),
        make_candidate("Unpacking", genres=["Puzzle"],
                       steam_appid=1135690, review_score=0.93, similarity=0.83),
        make_candidate("A Short Hike", genres=["Adventure"],
                       steam_appid=1055540, review_score=0.97, similarity=0.8),
    ]
