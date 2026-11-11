"""LLMService tests: the keyless fallback, and the TM11-69 prompt and parsing."""

from __future__ import annotations

import json

import pytest

from api.services.llm import (
    MAX_EXPLANATION_CHARS,
    LLMService,
    _build_messages,
    _picks_to_recs,
    clamp_recommendation_count,
    normalise_explanation,
)
from api.tests.conftest import make_candidate

pytestmark = pytest.mark.asyncio


async def test_keyless_fallback_produces_n_nonempty_reasons(candidates):
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)
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
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)
    query = "cozy farming"
    recs = await llm.rank(query, candidates, n=1)
    reason = recs[0].reason
    assert query in reason
    # First candidate has genres Simulation/RPG — at least one should appear.
    assert any(g in reason for g in candidates[0].genres)


async def test_rank_handles_fewer_candidates_than_n(candidates):
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)
    recs = await llm.rank("anything", candidates[:2], n=3)
    assert len(recs) == 2


async def test_rank_empty_candidates_returns_empty():
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)
    assert await llm.rank("anything", [], n=3) == []



# TM11-69 / REQ015: a ranking is 3 to 5 games.

@pytest.mark.parametrize("asked, expected", [(1, 3), (3, 3), (4, 4), (5, 5), (9, 5)])
async def test_count_is_clamped_to_the_req015_range(asked, expected):
    assert clamp_recommendation_count(asked) == expected


async def test_rank_never_returns_more_than_five(candidates):
    many = candidates + [make_candidate(f"Extra {i}", genres=["Indie"]) for i in range(5)]
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)

    recs = await llm.rank("anything", many, n=8)

    assert [r.rank for r in recs] == [1, 2, 3, 4, 5]


async def test_rank_asks_for_at_least_three(candidates):
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)

    recs = await llm.rank("anything", candidates, n=1)

    assert len(recs) == 3


# TM11-69 AC-01: the prompt asks for ranked titles, each with a one or two
# sentence explanation.

async def test_prompt_lists_every_candidate_by_index_and_title(candidates):
    system, user = _build_messages("cozy farming", candidates, 3)

    payload = user.split("Candidates (JSON):\n", 1)[1].split("\n\n", 1)[0]
    listed = json.loads(payload)
    assert [(c["index"], c["title"]) for c in listed] == [
        (i, c.title) for i, c in enumerate(candidates)
    ]
    assert "Request: cozy farming" in user


async def test_prompt_asks_for_ranked_titles_with_short_explanations(candidates):
    system, user = _build_messages("cozy farming", candidates, 4)

    assert "exactly 4 games" in user
    assert '"rank"' in user and '"title"' in user and '"explanation"' in user
    assert "one or two sentences" in user
    assert "best match first" in user


async def test_prompt_forbids_games_outside_the_list(candidates):
    system, _ = _build_messages("anything", candidates, 3)

    assert "Only choose games from the candidate list" in system
    assert "Never suggest a game that is not on the list" in system


async def test_explanation_key_is_read_and_reason_still_accepted(candidates):
    data = {"recommendations": [
        {"rank": 1, "index": 1, "title": "Coffee Talk", "explanation": "Chatty and calm."},
        {"index": 0, "reason": "Older response shape."},
    ]}

    recs = _picks_to_recs(data, candidates, "cozy", 2)

    assert [(r.title, r.reason) for r in recs] == [
        ("Coffee Talk", "Chatty and calm."), ("Stardew Valley", "Older response shape."),
    ]


# TM11-69 AC-01: each explanation is one or two sentences.

async def test_a_long_explanation_keeps_its_first_two_sentences():
    text = "It is calm. It has no fail states. It also has fishing. And cats."

    assert normalise_explanation(text) == "It is calm. It has no fail states."


async def test_short_explanations_and_closing_quotes_are_kept_intact():
    assert normalise_explanation("A gentle farming sim.") == "A gentle farming sim."
    assert normalise_explanation('Fits "cozy." Truly relaxing! Extra.') == (
        'Fits "cozy." Truly relaxing!'
    )


async def test_whitespace_is_collapsed_and_blank_becomes_empty():
    assert normalise_explanation("  Calm \n\n and   slow.  ") == "Calm and slow."
    assert normalise_explanation("   \n ") == ""


async def test_one_run_on_sentence_is_capped_at_a_word_boundary():
    text = "This game " + "really " * 80 + "fits."

    out = normalise_explanation(text)

    assert len(out) <= MAX_EXPLANATION_CHARS + 1
    assert out.endswith("…")
    assert not out[:-1].endswith(" ")


async def test_parsed_picks_are_normalised_and_blank_ones_synthesized(candidates):
    data = {"recommendations": [
        {"index": 0, "title": "Stardew Valley",
         "explanation": "Farming. Fishing. Friendship. Festivals."},
        {"index": 1, "title": "Coffee Talk", "explanation": "   "},
    ]}

    recs = _picks_to_recs(data, candidates, "cozy", 2)

    assert recs[0].reason == "Farming. Fishing."
    assert "Coffee Talk" in recs[1].reason and recs[1].reason.strip()
