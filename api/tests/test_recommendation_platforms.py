"""Recommendations carry the stores each game is on (TM11-75, REQ015).

The Discover result card lists a game's platforms, so ranking has to pass
GameCandidate.platforms through to each Recommendation. Offline: no LLM key,
so the deterministic ranker answers, and rank order is the candidates' order.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from api.models import GameCandidate, Recommendation
from api.services.llm import LLMService


def candidate(title: str, platforms: list[str]) -> GameCandidate:
    return GameCandidate(game_id=uuid4(), title=title, platforms=platforms)


@pytest.mark.asyncio
async def test_each_recommendation_keeps_its_games_platforms_in_rank_order():
    games = [
        candidate("Hades", ["steam", "xbox", "epic"]),
        candidate("Celeste", ["steam"]),
        candidate("A catalogue game with no store data", []),
    ]

    recs = await LLMService(gemini_api_key=None, anthropic_api_key=None).rank("roguelike", games)

    assert [r.rank for r in recs] == [1, 2, 3]
    assert [r.title for r in recs] == [g.title for g in games]
    assert [r.platforms for r in recs] == [["steam", "xbox", "epic"], ["steam"], []]


def test_platforms_default_to_an_empty_list_for_older_callers():
    rec = Recommendation(rank=1, title="Hades", reason="Fast action roguelike.")
    assert rec.platforms == []


def test_a_recommendations_platforms_are_its_own_copy():
    game = candidate("Hades", ["steam"])
    from api.services.llm import _to_recommendation

    rec = _to_recommendation(1, game, "Fast action roguelike.")
    rec.platforms.append("xbox")

    assert game.platforms == ["steam"]
