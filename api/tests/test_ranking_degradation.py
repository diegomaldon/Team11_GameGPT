"""Retry and graceful degradation when ranking fails (TM11-72, REQ040).

One group per acceptance criterion. Gemini is faked at the HTTP layer, so the
real LLMService retry loop runs; embedding, search and ownership are faked so
the integration test needs no model, database or network.
"""

from __future__ import annotations

import json
import logging
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
from api.services.llm import LLMService
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
