"""Owned games are dropped before the LLM ranks anything (TM11-66, REQ007).

Offline: the vector store, the LLM and the owned_games connection are faked.
Each test is named for the acceptance criterion it covers:

  AC-01  the dedup service filters candidates before the LLM, not after
  AC-02  a title owned on two platforms is never recommended
  AC-03  the filter adds under 200 ms (one query; the refill only checks new games)
  AC-04  a fully filtered candidate set gets a graceful fallback, not an empty response
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.main import create_app
from api.models import GameCandidate, Recommendation
from api.observability.stage_timings import StageTimings
from api.routers import recommend as recommend_router
from api.services import deduplication
from api.services.deduplication import DeduplicationService
from api.services.query_parser import QueryParser
from api.services.rag_pipeline import ALL_OWNED_NOTICE, RAGPipeline, RecommendOutcome

USER = UUID("00000000-0000-0000-0000-000000000066")


def catalogue(size: int) -> list[GameCandidate]:
    """`size` games, most similar first, so retrieval order is the list order."""
    return [
        GameCandidate(game_id=uuid4(), title=f"Game {i:03}", similarity=1 - i / 1000)
        for i in range(size)
    ]


async def _no_catalogue():
    return None


class FakeEmbedding:
    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * 1536


class FakeVectorStore:
    def __init__(self, games: list[GameCandidate]) -> None:
        self.games = games
        self.k_seen: list[int] = []

    async def top_k(self, embedding, k: int = 20, filters=None):
        self.k_seen.append(k)
        return self.games[:k]


class FakeDeduplication:
    """Owns the games in `owned`, and records every call in `calls`."""

    def __init__(self, owned: set[UUID], calls: list[str]) -> None:
        self.owned = owned
        self.calls = calls
        self.checked: list[list[UUID]] = []

    async def filter_owned(self, user_id, candidates):
        self.calls.append("filter")
        self.checked.append([c.game_id for c in candidates])
        return [c for c in candidates if c.game_id not in self.owned]


class FakeLLM:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.seen: list[GameCandidate] | None = None

    async def rank(self, query, candidates, n: int = 3):
        self.calls.append("rank")
        self.seen = list(candidates)
        return [
            Recommendation(rank=i + 1, game_id=c.game_id, title=c.title, reason=f"fits {query}")
            for i, c in enumerate(candidates[:n])
        ]


def pipeline(games, dedup, llm, *, k=20, refill_k=100) -> RAGPipeline:
    return RAGPipeline(
        FakeEmbedding(), FakeVectorStore(games), dedup, llm,
        k=k, n=3, refill_k=refill_k, parser=QueryParser(load_titles=_no_catalogue),
    )


# ── AC-01: filter before the model sees candidates ───────────────────────────


@pytest.mark.asyncio
async def test_ac01_the_filter_runs_before_the_llm_and_the_llm_never_sees_an_owned_game():
    games = catalogue(30)
    owned = {g.game_id for g in games[:5]}
    calls: list[str] = []
    llm = FakeLLM(calls)

    recs = await pipeline(games, FakeDeduplication(owned, calls), llm).recommend(USER, "cozy")

    assert calls == ["filter", "rank"]
    assert not {c.game_id for c in llm.seen} & owned
    assert not {r.game_id for r in recs} & owned
    assert [r.title for r in recs] == ["Game 005", "Game 006", "Game 007"]


# ── AC-02: the same title owned on two platforms ─────────────────────────────


class FakeCursor:
    def __init__(self, rows) -> None:
        self.rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params=None):
        self.params = params

    async def fetchall(self):
        # Like the real join, only rows for the game_ids asked about come back.
        asked = set(self.params[1])
        return [row for row in self.rows if row[0] in asked]


@pytest.fixture
def owned_games(monkeypatch):
    """Fake hosted owned_games joined to platform_accounts: (game_id, platform) rows."""

    def install(rows: list[tuple[UUID, str]]) -> None:
        cursor = FakeCursor(rows)

        class Conn:
            def cursor(self):
                return cursor

        @asynccontextmanager
        async def connection():
            yield Conn()

        async def catalogue_shape():
            return "hosted"

        monkeypatch.setattr(deduplication, "connection", connection)
        monkeypatch.setattr(deduplication, "catalogue_shape", catalogue_shape)

    return install


@pytest.mark.asyncio
async def test_ac02_a_title_owned_on_steam_and_xbox_is_never_recommended(owned_games):
    games = catalogue(30)
    hades = games[0]  # the best match for the query
    owned_games([(hades.game_id, "STEAM"), (hades.game_id, "XBOX")])
    calls: list[str] = []
    llm = FakeLLM(calls)

    recs = await pipeline(games, DeduplicationService(), llm).recommend(USER, "roguelike")

    assert hades.game_id not in {c.game_id for c in llm.seen}
    assert hades.game_id not in {r.game_id for r in recs}
    assert len(recs) == 3
    # Owned twice, dropped once: every other candidate is still there, in order.
    assert [c.game_id for c in llm.seen] == [g.game_id for g in games[1:20]]
    # And the badge data still shows both platforms.
    assert await DeduplicationService().owned_platforms(USER, [hades]) == {
        hades.game_id: ("steam", "xbox")
    }


@pytest.mark.asyncio
async def test_ac02_owned_on_two_platforms_across_a_refill_is_still_dropped(owned_games):
    games = catalogue(60)
    rows = [(g.game_id, p) for g in games[:20] for p in ("STEAM", "XBOX")]
    rows += [(games[20].game_id, "STEAM"), (games[20].game_id, "EPIC")]
    owned_games(rows)
    llm = FakeLLM([])

    outcome = await pipeline(games, DeduplicationService(), llm).recommend_outcome(USER, "rpg")

    assert [r.title for r in outcome.recommendations] == ["Game 021", "Game 022", "Game 023"]
    assert outcome.notice is None


# ── AC-03: the filter adds under 200 ms ──────────────────────────────────────


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000


@pytest.mark.asyncio
async def test_ac03_the_common_path_filters_once_with_no_refill():
    games = catalogue(30)
    calls: list[str] = []
    store = FakeVectorStore(games)
    dedup = FakeDeduplication({games[0].game_id}, calls)
    p = RAGPipeline(
        FakeEmbedding(), store, dedup, FakeLLM(calls), k=20, n=3,
        parser=QueryParser(load_titles=_no_catalogue),
    )

    await p.recommend(USER, "cozy")

    assert calls == ["filter", "rank"]
    assert len(store.k_seen) == 1  # one retrieval, no refill


@pytest.mark.asyncio
async def test_ac03_the_refill_only_checks_games_the_first_pass_had_not():
    games = catalogue(150)
    owned = {g.game_id for g in games[:20]}
    calls: list[str] = []
    dedup = FakeDeduplication(owned, calls)

    await pipeline(games, dedup, FakeLLM(calls)).recommend(USER, "cozy")

    first, second = dedup.checked
    assert first == [g.game_id for g in games[:20]]
    assert second == [g.game_id for g in games[20:100]]
    assert not set(first) & set(second)


@pytest.mark.asyncio
async def test_ac03_refill_time_adds_to_the_retrieve_and_filter_stages():
    games = catalogue(150)
    owned = {g.game_id for g in games[:20]}
    clock = FakeClock()
    calls: list[str] = []
    dedup = FakeDeduplication(owned, calls)
    p = pipeline(games, dedup, FakeLLM(calls))

    async def slow_filter(user_id, candidates, _real=dedup.filter_owned):
        clock.advance(15)
        return await _real(user_id, candidates)

    dedup.filter_owned = slow_filter
    timings = StageTimings(clock=clock)

    await p.recommend(USER, "cozy", timings=timings)

    assert timings.log_fields()["filter_ms"] == 30.0  # both passes counted
    assert timings.log_fields()["filter_ms"] < 200


# ── AC-04: a fully filtered set falls back gracefully ────────────────────────


@pytest.mark.asyncio
async def test_ac04_when_the_first_k_are_all_owned_a_deeper_search_refills():
    games = catalogue(150)
    owned = {g.game_id for g in games[:20]}
    calls: list[str] = []
    llm = FakeLLM(calls)

    outcome = await pipeline(games, FakeDeduplication(owned, calls), llm).recommend_outcome(
        USER, "cozy"
    )

    assert calls == ["filter", "filter", "rank"]
    assert [r.title for r in outcome.recommendations] == ["Game 020", "Game 021", "Game 022"]
    assert outcome.notice is None
    assert not {c.game_id for c in llm.seen} & owned


@pytest.mark.asyncio
async def test_ac04_a_short_first_pass_is_topped_up_and_keeps_its_order():
    games = catalogue(150)
    owned = {g.game_id for g in games[:20]} - {games[7].game_id}
    llm = FakeLLM([])

    recs = await pipeline(games, FakeDeduplication(owned, []), llm).recommend(USER, "cozy")

    assert [r.title for r in recs] == ["Game 007", "Game 020", "Game 021"]


@pytest.mark.asyncio
async def test_ac04_owning_every_match_returns_a_notice_and_skips_the_llm(caplog):
    games = catalogue(150)
    owned = {g.game_id for g in games}
    calls: list[str] = []
    timings = StageTimings()

    with caplog.at_level(logging.INFO, logger="gamegpt.latency"):
        outcome = await pipeline(games, FakeDeduplication(owned, calls), FakeLLM(calls)) \
            .recommend_outcome(USER, "cozy", timings=timings)

    assert outcome == RecommendOutcome(recommendations=[], notice=ALL_OWNED_NOTICE)
    assert outcome.notice.code == "all_owned"
    assert outcome.notice.message.strip()
    assert "rank" not in calls
    assert timings.log_fields()["rank_ms"] is None
    assert any(r.getMessage() == "recommend.all_owned" for r in caplog.records)


@pytest.mark.asyncio
async def test_ac04_a_small_catalogue_that_is_all_owned_still_gets_the_notice():
    games = catalogue(5)
    owned = {g.game_id for g in games}

    outcome = await pipeline(games, FakeDeduplication(owned, []), FakeLLM([])).recommend_outcome(
        USER, "cozy"
    )

    assert outcome.notice == ALL_OWNED_NOTICE


@pytest.mark.asyncio
async def test_ac04_recommend_still_returns_a_plain_list():
    games = catalogue(5)
    owned = {g.game_id for g in games}

    recs = await pipeline(games, FakeDeduplication(owned, []), FakeLLM([])).recommend(USER, "x")

    assert recs == []


class AllOwnedPipeline:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def recommend_outcome(self, user_id, query, *, timings=None):
        return RecommendOutcome(recommendations=[], notice=ALL_OWNED_NOTICE)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    async def no_save(**_):
        return None

    monkeypatch.setattr(repositories, "save_query_history", no_save)
    return TestClient(create_app())


def test_ac04_the_api_answers_200_with_the_notice(monkeypatch, client):
    monkeypatch.setattr(recommend_router, "RAGPipeline", AllOwnedPipeline)

    resp = client.post("/api/recommend", json={"query": "cozy farming game"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["recommendations"] == []
    assert body["notice"] == {"code": "all_owned", "message": ALL_OWNED_NOTICE.message}


def test_ac04_a_normal_response_has_no_notice(monkeypatch, client):
    class OnePick(AllOwnedPipeline):
        async def recommend_outcome(self, user_id, query, *, timings=None):
            rec = Recommendation(rank=1, title="Stardew Valley", reason="Cozy farming.")
            return RecommendOutcome(recommendations=[rec])

    monkeypatch.setattr(recommend_router, "RAGPipeline", OnePick)

    resp = client.post("/api/recommend", json={"query": "cozy farming game"})

    assert resp.status_code == 200
    assert resp.json()["notice"] is None
