"""LLMService keyless deterministic fallback tests."""

from __future__ import annotations

import pytest

from api.services.llm import LLMService

pytestmark = pytest.mark.asyncio


async def test_keyless_fallback_produces_n_nonempty_reasons(candidates):
    llm = LLMService(api_key=None)
    assert llm.offline is True

    recs = await llm.rank("a chill game for a podcast night", candidates, n=3)

    assert len(recs) == 3
    assert [r.rank for r in recs] == [1, 2, 3]
    for r in recs:
        assert r.reason and r.reason.strip()
    # Carries identifiers from the candidate through to the recommendation.
    top = recs[0]
    assert top.title == candidates[0].title
    assert top.game_id == candidates[0].game_id
    assert top.steam_appid == candidates[0].steam_appid
    assert top.review_score == candidates[0].review_score


async def test_reason_references_query_and_traits(candidates):
    llm = LLMService(api_key=None)
    query = "cozy farming"
    recs = await llm.rank(query, candidates, n=1)
    reason = recs[0].reason
    assert query in reason
    # First candidate has genres Simulation/RPG — at least one should appear.
    assert any(g in reason for g in candidates[0].genres)


async def test_rank_handles_fewer_candidates_than_n(candidates):
    llm = LLMService(api_key=None)
    recs = await llm.rank("anything", candidates[:2], n=3)
    assert len(recs) == 2


async def test_rank_empty_candidates_returns_empty():
    llm = LLMService(api_key=None)
    assert await llm.rank("anything", [], n=3) == []
