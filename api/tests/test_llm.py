"""LLMService tests: the keyless fallback, and the TM11-69 prompt and parsing."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from api.observability.logging_config import JsonFormatter
from api.services import llm as llm_module
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


# TM11-69 AC-03: output is constrained to the retrieved candidate set.

def _pick(index, title, explanation="Fits.", **extra):
    return {"index": index, "title": title, "explanation": explanation, **extra}


async def test_a_made_up_title_is_dropped_even_with_a_valid_index(candidates, caplog):
    data = {"recommendations": [
        _pick(0, "Stardew Valley"),
        _pick(1, "Animal Crossing: New Horizons"),  # not retrieved
        _pick(2, "Dorfromantik"),
    ]}

    with caplog.at_level(logging.WARNING, logger="gamegpt.llm"):
        recs = _picks_to_recs(data, candidates, "cozy", 3)

    titles = [r.title for r in recs]
    assert "Animal Crossing: New Horizons" not in titles
    assert titles[:2] == ["Stardew Valley", "Dorfromantik"]
    [record] = [r for r in caplog.records if r.msg == "llm.picks_rejected"]
    assert record.rejected_count == 1
    assert record.rejected_titles == ["Animal Crossing: New Horizons"]


async def test_out_of_range_and_non_numeric_indexes_are_dropped(candidates):
    data = {"recommendations": [
        {"index": 99, "explanation": "No such candidate."},
        {"index": "two", "explanation": "Not a number."},
        {"index": True, "explanation": "A bool is not an index."},
        "not even an object",
        _pick(3, "Unpacking"),
    ]}

    recs = _picks_to_recs(data, candidates, "cozy", 3)

    assert recs[0].title == "Unpacking"
    assert recs[0].reason == "Fits."


async def test_the_title_wins_when_the_index_points_elsewhere(candidates):
    data = {"recommendations": [_pick(0, "a short hike", "Tiny and lovely.")]}

    recs = _picks_to_recs(data, candidates, "cozy", 3)

    assert (recs[0].title, recs[0].reason) == ("A Short Hike", "Tiny and lovely.")
    assert recs[0].game_id == candidates[4].game_id


async def test_duplicate_picks_are_counted_once(candidates):
    data = {"recommendations": [
        _pick(0, "Stardew Valley", "First."),
        _pick(0, "Stardew Valley", "Again."),
        _pick(1, "Coffee Talk"),
    ]}

    recs = _picks_to_recs(data, candidates, "cozy", 3)

    assert [r.title for r in recs].count("Stardew Valley") == 1
    assert recs[0].reason == "First."


async def test_a_short_answer_is_filled_from_unpicked_candidates(candidates, caplog):
    data = {"recommendations": [_pick(2, "Dorfromantik")]}

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        recs = _picks_to_recs(data, candidates, "cozy", 3)

    assert [r.title for r in recs] == ["Dorfromantik", "Stardew Valley", "Coffee Talk"]
    assert [r.rank for r in recs] == [1, 2, 3]
    assert all(r.reason.strip() for r in recs)
    assert any(r.msg == "llm.picks_filled" and r.filled_count == 2 for r in caplog.records)


async def test_the_models_rank_field_orders_the_result(candidates):
    data = {"recommendations": [
        _pick(1, "Coffee Talk", rank=2),
        _pick(0, "Stardew Valley", rank=1),
        _pick(2, "Dorfromantik", rank=3),
    ]}

    recs = _picks_to_recs(data, candidates, "cozy", 3)

    assert [r.title for r in recs] == ["Stardew Valley", "Coffee Talk", "Dorfromantik"]


@pytest.mark.parametrize("data", [
    {"recommendations": []},
    {"recommendations": "Stardew Valley"},
    {"recommendations": [_pick(0, "Hollow Knight"), _pick(1, "Celeste")]},
    ["not", "an", "object"],
])
async def test_nothing_usable_raises_so_the_provider_is_retried(candidates, data):
    with pytest.raises(ValueError):
        _picks_to_recs(data, candidates, "cozy", 3)


async def test_every_result_comes_from_the_candidates_given(candidates):
    allowed = {c.game_id for c in candidates}
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)
    offline = await llm.rank("anything", candidates, n=5)
    parsed = _picks_to_recs(
        {"recommendations": [_pick(4, "A Short Hike"), _pick(0, "Portal 2")]},
        candidates, "anything", 5,
    )

    for recs in (offline, parsed):
        assert {r.game_id for r in recs} <= allowed


# TM11-69 AC-02: each result carries rank, explanation and generated_at.

async def test_every_result_is_stamped_with_one_utc_generated_at(candidates):
    before = datetime.now(timezone.utc)
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)

    recs = await llm.rank("cozy", candidates, n=3)

    after = datetime.now(timezone.utc)
    stamps = {r.generated_at for r in recs}
    assert len(stamps) == 1
    [stamp] = stamps
    assert stamp.tzinfo is not None
    assert before <= stamp <= after


async def test_a_parsed_result_has_the_columns_of_a_recommendations_row(candidates):
    async def fake_provider(query, pool, n, **_):
        return _picks_to_recs(
            {"recommendations": [_pick(1, "Coffee Talk", "Calm chats over coffee.")]},
            pool, query, n,
        )

    llm = LLMService(anthropic_api_key=None, gemini_api_key="test-key")
    llm._rank_with_gemini = fake_provider

    top = (await llm.rank("cozy", candidates, n=3))[0]

    assert (top.rank, top.reason) == (1, "Calm chats over coffee.")
    assert top.game_id == candidates[1].game_id
    assert top.generated_at is not None


async def test_generated_at_is_sent_in_the_response_body(candidates):
    llm = LLMService(anthropic_api_key=None, gemini_api_key=None)

    [first, *_] = await llm.rank("cozy", candidates, n=3)

    body = first.model_dump(mode="json")
    assert datetime.fromisoformat(body["generated_at"]) == first.generated_at


# TM11-69 AC-04: token usage is logged.

GEMINI_KEY = "test-gemini-key-not-real"


def _gemini_body(picks: list[dict] | str, usage: dict | None = None) -> dict:
    text = picks if isinstance(picks, str) else json.dumps({"recommendations": picks})
    body: dict = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if usage is not None:
        body["usageMetadata"] = usage
    return body


def _fake_gemini(monkeypatch, *bodies: dict) -> list[httpx.Request]:
    """Serve each body in turn to LLMService's Gemini call; return the requests."""
    seen: list[httpx.Request] = []
    replies = iter(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=next(replies))

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        llm_module.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return seen


def _records(caplog, msg: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.msg == msg]


USAGE = {"promptTokenCount": 812, "candidatesTokenCount": 96, "totalTokenCount": 908}


async def test_gemini_token_usage_is_logged_per_attempt_and_per_call(
    monkeypatch, caplog, candidates
):
    _fake_gemini(monkeypatch, _gemini_body([_pick(0, "Stardew Valley")], USAGE))
    llm = LLMService(gemini_api_key=GEMINI_KEY, gemini_model="gemini-test",
                     anthropic_api_key=None)

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        recs = await llm.rank("cozy", candidates, n=3)

    assert recs[0].title == "Stardew Valley"
    [usage] = _records(caplog, "llm.usage")
    assert (usage.provider, usage.model, usage.attempt) == ("gemini", "gemini-test", 1)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (812, 96, 908)
    [ranked] = _records(caplog, "llm.ranked")
    assert (ranked.provider, ranked.attempts, ranked.total_tokens) == ("gemini", 1, 908)


async def test_a_failed_parse_still_logs_the_tokens_it_spent(monkeypatch, caplog, candidates):
    _fake_gemini(
        monkeypatch,
        _gemini_body("Sorry, here are some games: Hollow Knight", USAGE),
        _gemini_body([_pick(1, "Coffee Talk")], USAGE),
    )
    llm = LLMService(gemini_api_key=GEMINI_KEY, anthropic_api_key=None)

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        recs = await llm.rank("cozy", candidates, n=3)

    assert recs[0].title == "Coffee Talk"
    assert [r.attempt for r in _records(caplog, "llm.usage")] == [1, 2]
    [failed] = _records(caplog, "llm.attempt_failed")
    assert (failed.provider, failed.error_type) == ("gemini", "ValueError")
    [ranked] = _records(caplog, "llm.ranked")
    assert (ranked.attempts, ranked.total_tokens) == (2, 2 * 908)


async def test_a_response_without_usage_logs_zero_rather_than_failing(
    monkeypatch, caplog, candidates
):
    _fake_gemini(monkeypatch, _gemini_body([_pick(0, "Stardew Valley")]))
    llm = LLMService(gemini_api_key=GEMINI_KEY, anthropic_api_key=None)

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        recs = await llm.rank("cozy", candidates, n=3)

    assert recs[0].title == "Stardew Valley"
    [usage] = _records(caplog, "llm.usage")
    assert usage.total_tokens == 0


async def test_anthropic_token_usage_is_logged(caplog, candidates):
    reply = json.dumps({"recommendations": [_pick(2, "Dorfromantik", "Calm tiles.")]})

    class FakeMessages:
        async def create(self, **_):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=reply)],
                usage=SimpleNamespace(input_tokens=700, output_tokens=80),
            )

    llm = LLMService(gemini_api_key=None, anthropic_api_key="test-anthropic-key",
                     anthropic_model="claude-test")
    llm._anthropic_client = SimpleNamespace(messages=FakeMessages())

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        recs = await llm.rank("cozy", candidates, n=3)

    assert recs[0].title == "Dorfromantik"
    [usage] = _records(caplog, "llm.usage")
    assert (usage.provider, usage.model) == ("anthropic", "claude-test")
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (700, 80, 780)


async def test_the_offline_ranker_logs_a_zero_token_call(caplog, candidates):
    llm = LLMService(gemini_api_key=None, anthropic_api_key=None)

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        await llm.rank("cozy", candidates, n=3)

    assert _records(caplog, "llm.usage") == []
    [ranked] = _records(caplog, "llm.ranked")
    assert (ranked.provider, ranked.attempts, ranked.total_tokens) == ("deterministic", 0, 0)


async def test_usage_lines_reach_the_json_log_unredacted_and_without_the_key(
    monkeypatch, caplog, candidates
):
    requests = _fake_gemini(monkeypatch, _gemini_body([_pick(0, "Stardew Valley")], USAGE))
    llm = LLMService(gemini_api_key=GEMINI_KEY, anthropic_api_key=None)

    with caplog.at_level(logging.INFO, logger="gamegpt.llm"):
        await llm.rank("cozy", candidates, n=3)

    assert requests[0].url.params["key"] == GEMINI_KEY  # the key was used...
    lines = [JsonFormatter().format(r) for r in caplog.records]
    assert all(GEMINI_KEY not in line for line in lines)  # ...and never logged
    usage = json.loads(next(line for line in lines if '"llm.usage"' in line))
    assert (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"]) == (
        812, 96, 908,
    )


async def test_a_non_string_explanation_is_synthesized_not_rendered(candidates):
    data = {"recommendations": [
        {"index": 0, "title": "Stardew Valley", "explanation": ["calm", "farming"]},
    ]}

    recs = _picks_to_recs(data, candidates, "cozy", 3)

    assert "[" not in recs[0].reason
    assert "Stardew Valley" in recs[0].reason


async def test_a_long_rejected_title_is_capped_in_the_log(candidates, caplog):
    data = {"recommendations": [_pick(0, "X" * 500), _pick(1, "Coffee Talk")]}

    with caplog.at_level(logging.WARNING, logger="gamegpt.llm"):
        _picks_to_recs(data, candidates, "cozy", 3)

    [record] = [r for r in caplog.records if r.msg == "llm.picks_rejected"]
    assert record.rejected_titles == ["X" * 100]


# PR #61 review (Diego): an abbreviation's full stop is not a sentence end.

@pytest.mark.parametrize("text, expected", [
    ("Inspired by Mr. Robot. Very tense.", "Inspired by Mr. Robot. Very tense."),
    ("Like Dr. Mario vs. Tetris. Fast. Third.", "Like Dr. Mario vs. Tetris. Fast."),
    ("A J. R. R. Tolkien-style epic. Huge world. Long.",
     "A J. R. R. Tolkien-style epic. Huge world."),
    ("Puzzles, e.g. sliding blocks. Calm. Third.", "Puzzles, e.g. sliding blocks. Calm."),
])
async def test_abbreviations_and_initials_do_not_end_a_sentence(text, expected):
    assert normalise_explanation(text) == expected


async def test_etc_still_ends_a_sentence():
    assert normalise_explanation("Farming, fishing, etc. Very calm. Third.") == (
        "Farming, fishing, etc. Very calm."
    )
