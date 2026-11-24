"""Retry and graceful degradation when ranking fails (TM11-72, REQ040).

One group per acceptance criterion. Gemini is faked at the HTTP layer, so the
real LLMService retry loop runs; embedding, search and ownership are faked so
the integration test needs no model, database or network.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.main import create_app
from api.models import GameCandidate
from api.routers import recommend as recommend_router
from api.services import llm as llm_module
from api.services import query_parser
from api.services.llm import RANK_DEADLINE_SECONDS, LLMService
from api.services.rag_pipeline import RANKING_DEGRADED_NOTICE, RAGPipeline

GEMINI_KEY = "test-gemini-key-not-real"
TITLES = ["Stardew Valley", "Coffee Talk", "Dorfromantik", "Unpacking", "A Short Hike"]


def _candidates() -> list[GameCandidate]:
    return [
        GameCandidate(game_id=uuid4(), title=t, description=f"{t} description",
                      genres=["Simulation"], platforms=["steam"], similarity=0.9 - i / 100)
        for i, t in enumerate(TITLES)
    ]


def _valid_body(candidates: list[GameCandidate]) -> dict:
    picks = [{"rank": r, "index": i, "title": candidates[i].title, "explanation": "Calm."}
             for r, i in ((1, 4), (2, 3), (3, 2))]
    text = json.dumps({"recommendations": picks})
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


MALFORMED = {"candidates": [{"content": {"parts": [{"text": "Sorry, I can't do JSON today"}]}}]}


def _fake_gemini(monkeypatch, *replies: httpx.Response) -> list[httpx.Request]:
    """Answer LLMService's Gemini calls with `replies` in turn; return the requests."""
    seen: list[httpx.Request] = []
    queue = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(queue)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        llm_module.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    return seen


def _gemini_llm() -> LLMService:
    return LLMService(gemini_api_key=GEMINI_KEY, gemini_model="gemini-test",
                      anthropic_api_key=None)


def _records(caplog, msg: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.msg == msg]


# ───── AC: malformed output retried once ─────


@pytest.mark.asyncio
async def test_malformed_output_is_retried_once_and_the_retry_is_used(monkeypatch):
    candidates = _candidates()
    seen = _fake_gemini(monkeypatch, httpx.Response(200, json=MALFORMED),
                        httpx.Response(200, json=_valid_body(candidates)))

    outcome = await _gemini_llm().rank_outcome("something calm", candidates, n=3)

    assert len(seen) == 2
    assert outcome.provider == "gemini"
    assert outcome.degraded is False
    assert [r.title for r in outcome.recommendations] == ["A Short Hike", "Unpacking",
                                                          "Dorfromantik"]


@pytest.mark.asyncio
async def test_a_provider_is_retried_once_not_more(monkeypatch):
    seen = _fake_gemini(monkeypatch, *[httpx.Response(200, json=MALFORMED)] * 5)

    await _gemini_llm().rank_outcome("something calm", _candidates(), n=3)

    assert len(seen) == 2  # one attempt + one retry, then no more Gemini calls


# ───── AC: second failure returns retrieval-only results with a clear notice ─────


@pytest.mark.asyncio
async def test_a_second_malformed_answer_falls_back_to_retrieval_order(monkeypatch):
    candidates = _candidates()
    _fake_gemini(monkeypatch, *[httpx.Response(200, json=MALFORMED)] * 2)

    outcome = await _gemini_llm().rank_outcome("something calm", candidates, n=3)

    assert outcome.degraded is True
    assert outcome.provider == "deterministic"
    assert [r.title for r in outcome.recommendations] == TITLES[:3]
    assert [r.rank for r in outcome.recommendations] == [1, 2, 3]
    assert all(r.reason.strip() for r in outcome.recommendations)


@pytest.mark.asyncio
async def test_provider_errors_degrade_the_same_way(monkeypatch):
    _fake_gemini(monkeypatch, httpx.Response(503, json={}), httpx.Response(500, json={}))

    outcome = await _gemini_llm().rank_outcome("something calm", _candidates(), n=3)

    assert outcome.degraded is True
    assert len(outcome.recommendations) == 3


@pytest.mark.asyncio
async def test_no_key_at_all_is_the_offline_ranker_not_a_degradation(caplog):
    caplog.set_level(logging.WARNING, logger="gamegpt.llm")
    llm = LLMService(gemini_api_key=None, anthropic_api_key=None)

    outcome = await llm.rank_outcome("something calm", _candidates(), n=3)

    assert outcome.provider == "deterministic"
    assert outcome.degraded is False
    assert _records(caplog, "llm.degraded") == []


@pytest.mark.asyncio
async def test_rank_still_returns_a_plain_list(monkeypatch):
    _fake_gemini(monkeypatch, *[httpx.Response(200, json=MALFORMED)] * 2)

    recs = await _gemini_llm().rank("something calm", _candidates(), n=3)

    assert [r.title for r in recs] == TITLES[:3]


@pytest.mark.asyncio
async def test_no_candidates_is_empty_and_not_degraded():
    outcome = await _gemini_llm().rank_outcome("anything", [], n=3)
    assert (outcome.recommendations, outcome.degraded) == ([], False)


def test_the_notice_says_the_results_are_unranked_search_matches():
    assert RANKING_DEGRADED_NOTICE.code == "ranking_degraded"
    assert "closest matches from search" in RANKING_DEGRADED_NOTICE.message
    assert "not a ranked list" in RANKING_DEGRADED_NOTICE.message


# ───── AC: degraded mode logged ─────


@pytest.mark.asyncio
async def test_degraded_mode_is_logged_with_what_failed(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="gamegpt.llm")
    _fake_gemini(monkeypatch, httpx.Response(200, json=MALFORMED), httpx.Response(503, json={}))

    await _gemini_llm().rank_outcome("something calm", _candidates(), n=3)

    [degraded] = _records(caplog, "llm.degraded")
    assert degraded.levelno == logging.WARNING
    assert degraded.providers == ["gemini"]
    assert degraded.attempts == 2
    assert degraded.error_types == ["UpstreamError", "ValueError"]
    assert degraded.result_count == 3
    [ranked] = _records(caplog, "llm.ranked")
    assert ranked.provider == "deterministic"
    # The request text never reaches the log line.
    assert "something calm" not in json.dumps(degraded.__dict__, default=str)


@pytest.mark.asyncio
async def test_a_successful_ranking_logs_no_degradation(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="gamegpt.llm")
    candidates = _candidates()
    _fake_gemini(monkeypatch, httpx.Response(200, json=_valid_body(candidates)))

    await _gemini_llm().rank_outcome("something calm", candidates, n=3)

    assert _records(caplog, "llm.degraded") == []


# ───── AC: integration test with the LLM stubbed to fail ─────


class _Embedding:
    async def embed_query(self, text):
        return [0.0, 1.0]


class _Store:
    def __init__(self, candidates):
        self.candidates = candidates

    async def top_k(self, embedding, k=20, filters=None):
        return self.candidates[:k]


class _NoneOwned:
    async def filter_owned(self, user_id, candidates):
        return list(candidates)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    async def no_save(**_):
        return None

    monkeypatch.setattr(repositories, "save_query_history", no_save)
    monkeypatch.setattr(query_parser, "has_db", lambda: False)  # no catalogue titles
    candidates = _candidates()
    monkeypatch.setattr(recommend_router, "EmbeddingService", _Embedding)
    monkeypatch.setattr(recommend_router, "VectorStore", lambda: _Store(candidates))
    monkeypatch.setattr(recommend_router, "DeduplicationService", _NoneOwned)
    monkeypatch.setattr(recommend_router, "LLMService", _gemini_llm)
    return TestClient(create_app())


def test_the_api_answers_200_with_search_results_and_the_notice_when_ranking_fails(
    monkeypatch, client, caplog,
):
    caplog.set_level(logging.INFO, logger="gamegpt.llm")
    seen = _fake_gemini(monkeypatch, *[httpx.Response(200, json=MALFORMED)] * 2)

    resp = client.post("/api/recommend", json={"query": "something calm to unwind"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["notice"] == {"code": "ranking_degraded",
                              "message": RANKING_DEGRADED_NOTICE.message}
    assert [r["title"] for r in body["recommendations"]] == TITLES[:3]
    assert all(r["reason"] for r in body["recommendations"])
    assert len(seen) == 2
    assert len(_records(caplog, "llm.degraded")) == 1


def test_the_api_answers_normally_when_the_retry_succeeds(monkeypatch, client):
    seen = _fake_gemini(monkeypatch, httpx.Response(503, json={}),
                        httpx.Response(200, json=_valid_body(_candidates())))

    resp = client.post("/api/recommend", json={"query": "something calm to unwind"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["notice"] is None
    assert [r["title"] for r in body["recommendations"]] == ["A Short Hike", "Unpacking",
                                                             "Dorfromantik"]
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_the_pipeline_adds_the_notice_only_when_ranking_degraded(monkeypatch):
    candidates = _candidates()
    monkeypatch.setattr(query_parser, "has_db", lambda: False)
    _fake_gemini(monkeypatch, *[httpx.Response(200, json=MALFORMED)] * 2,
                 httpx.Response(200, json=_valid_body(candidates)))
    pipeline = RAGPipeline(_Embedding(), _Store(candidates), _NoneOwned(), _gemini_llm())

    degraded = await pipeline.recommend_outcome(uuid4(), "something calm")
    ranked = await pipeline.recommend_outcome(uuid4(), "something calm")

    assert degraded.notice == RANKING_DEGRADED_NOTICE
    assert ranked.notice is None


# ───── A hung provider degrades within one deadline (TM11-72 + TM11-77) ─────


def _hanging_gemini(monkeypatch, calls: list[str]) -> None:
    async def hang(self, query, candidates, n, *, tally):
        calls.append("gemini")
        await asyncio.sleep(60)  # never answers in time

    monkeypatch.setattr(LLMService, "_rank_with_gemini", hang)


@pytest.mark.asyncio
async def test_a_hung_provider_degrades_at_the_deadline_not_after_its_own_timeout(
    monkeypatch, caplog,
):
    caplog.set_level(logging.INFO, logger="gamegpt.llm")
    calls: list[str] = []
    _hanging_gemini(monkeypatch, calls)
    llm = LLMService(gemini_api_key=GEMINI_KEY, anthropic_api_key=None,
                     rank_deadline_seconds=0.2)

    started = time.monotonic()
    outcome = await llm.rank_outcome("something calm", _candidates(), n=3)
    elapsed = time.monotonic() - started

    assert outcome.degraded is True
    assert [r.title for r in outcome.recommendations] == TITLES[:3]
    assert elapsed < 1.0
    # The first attempt used up the deadline, so no retry was started.
    assert calls == ["gemini"]
    [degraded] = _records(caplog, "llm.degraded")
    assert degraded.error_types == ["TimeoutError"]


@pytest.mark.asyncio
async def test_a_fast_failure_still_gets_its_retry_inside_the_deadline(monkeypatch):
    candidates = _candidates()
    seen = _fake_gemini(monkeypatch, httpx.Response(503, json={}),
                        httpx.Response(200, json=_valid_body(candidates)))

    outcome = await _gemini_llm().rank_outcome("something calm", candidates, n=3)

    assert len(seen) == 2
    assert outcome.degraded is False


def test_the_default_deadline_keeps_a_degraded_recommend_inside_req040():
    # PR #67 review: the deadline is the rank stage's own budget, so the earlier
    # stages' budgets plus it stay within REQ040's 10 s, and well inside the web
    # client's 15 s (TM11-77's RECOMMEND_TIMEOUT_MS).
    from api.observability.stage_timings import STAGE_BUDGET_MS, TOTAL_BUDGET_MS

    assert RANK_DEADLINE_SECONDS == STAGE_BUDGET_MS["rank"] / 1000
    before_rank_s = sum(v for k, v in STAGE_BUDGET_MS.items() if k != "rank") / 1000
    assert before_rank_s + RANK_DEADLINE_SECONDS <= TOTAL_BUDGET_MS / 1000


@pytest.mark.asyncio
async def test_a_hung_first_provider_still_leaves_the_next_one_time_to_answer(monkeypatch):
    # PR #67 review: with both keys set, a hung Gemini used to spend the whole
    # deadline, so Anthropic never got a try.
    calls: list[str] = []
    _hanging_gemini(monkeypatch, calls)
    candidates = _candidates()

    async def anthropic_answers(self, query, cands, n, *, tally):
        calls.append("anthropic")
        return _picks_from_valid_body(cands)

    monkeypatch.setattr(LLMService, "_rank_with_anthropic", anthropic_answers)
    llm = LLMService(gemini_api_key=GEMINI_KEY, anthropic_api_key="test-anthropic-key",
                     rank_deadline_seconds=0.4)

    started = time.monotonic()
    outcome = await llm.rank_outcome("something calm", candidates, n=3)

    assert outcome.provider == "anthropic"
    assert outcome.degraded is False
    assert calls == ["gemini", "anthropic"]
    assert time.monotonic() - started < 1.0


def _picks_from_valid_body(candidates):
    from api.services.llm import _picks_to_recs

    data = json.loads(_valid_body(candidates)["candidates"][0]["content"]["parts"][0]["text"])
    return _picks_to_recs(data, candidates, "something calm", 3)


def test_the_anthropic_client_does_not_retry_on_its_own(monkeypatch):
    # PR #67 review: the SDK retries twice by default, on top of our one retry.
    import anthropic

    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    LLMService(gemini_api_key=None, anthropic_api_key="test-anthropic-key")._anthropic()
    assert seen["max_retries"] == 0
