"""RAGPipeline orchestration tests with fully faked collaborators.

The timing tests at the end are TM11-68 (REQ040).
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest

from api.models import GameCandidate, Recommendation
from api.observability.stage_timings import StageTimings
from api.services.hybrid_retrieval import DEFAULT_POOL_SIZE
from api.services.query_parser import QueryParser
from api.services.rag_pipeline import RAGPipeline

pytestmark = pytest.mark.asyncio

DEV_USER = UUID("00000000-0000-0000-0000-000000000001")


class FakeEmbedding:
    def __init__(self):
        self.calls: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return [0.1] * 1536

    async def embed_texts(self, texts):
        return [[0.1] * 1536 for _ in texts]


class FakeVectorStore:
    def __init__(self, candidates: list[GameCandidate]):
        self._candidates = candidates
        self.k_seen: int | None = None

    async def top_k(self, embedding, k: int = 20, filters=None):
        self.k_seen = k
        return self._candidates[:k]


class FakeDeduplication:
    def __init__(self, owned_titles: set[str]):
        self._owned = owned_titles

    async def filter_owned(self, user_id, candidates):
        return [c for c in candidates if c.title not in self._owned]


async def _no_catalogue():
    return None


# Offline: the default parser would read the catalogue from DATABASE_URL.
OFFLINE_PARSER = QueryParser(load_titles=_no_catalogue)


class FakeLLM:
    def __init__(self):
        self.seen_candidates: list[GameCandidate] | None = None

    async def rank(self, query, candidates, n: int = 3):
        self.seen_candidates = candidates
        return [
            Recommendation(
                rank=i + 1,
                game_id=c.game_id,
                title=c.title,
                reason=f"ranked for {query}",
                steam_appid=c.steam_appid,
                review_score=c.review_score,
            )
            for i, c in enumerate(candidates[:n])
        ]


async def test_pipeline_returns_three_ranked_results(candidates):
    embedding = FakeEmbedding()
    vector_store = FakeVectorStore(candidates)
    dedup = FakeDeduplication(owned_titles=set())
    llm = FakeLLM()
    pipeline = RAGPipeline(embedding, vector_store, dedup, llm, k=20, n=3, parser=OFFLINE_PARSER)

    recs = await pipeline.recommend(DEV_USER, "a chill game for a podcast night")

    assert len(recs) == 3
    assert [r.rank for r in recs] == [1, 2, 3]
    assert all(r.reason.strip() for r in recs)
    assert embedding.calls == ["a chill game for a podcast night"]
    # TM11-65: each search pulls a pool, and k=20 candidates go on to dedup and the LLM.
    assert vector_store.k_seen == DEFAULT_POOL_SIZE
    assert len(llm.seen_candidates) <= 20


async def test_pipeline_excludes_owned_games(candidates):
    owned = {"Stardew Valley"}  # the top candidate is owned
    embedding = FakeEmbedding()
    vector_store = FakeVectorStore(candidates)
    dedup = FakeDeduplication(owned_titles=owned)
    llm = FakeLLM()
    pipeline = RAGPipeline(embedding, vector_store, dedup, llm, k=20, n=3, parser=OFFLINE_PARSER)

    recs = await pipeline.recommend(DEV_USER, "cozy")

    titles = {r.title for r in recs}
    assert "Stardew Valley" not in titles
    # The LLM only ever saw the de-duplicated candidate set.
    assert all(c.title != "Stardew Valley" for c in llm.seen_candidates)


async def test_pipeline_uses_keyless_services_end_to_end(candidates):
    """Real EmbeddingService + LLMService (keyless), fake retrieval/dedup."""
    from api.services.embedding import EmbeddingService
    from api.services.llm import LLMService

    embedding = EmbeddingService(use_stub=True)
    vector_store = FakeVectorStore(candidates)
    dedup = FakeDeduplication(owned_titles=set())
    llm = LLMService(gemini_api_key=None, anthropic_api_key=None)
    pipeline = RAGPipeline(embedding, vector_store, dedup, llm, k=20, n=3, parser=OFFLINE_PARSER)

    recs = await pipeline.recommend(DEV_USER, "relaxing game")

    assert len(recs) == 3
    assert all(r.reason.strip() for r in recs)


# TM11-68 (REQ040): each stage is timed and logged, on success and on failure.

class FakeClock:
    def __init__(self) -> None:
        self.now_seconds = 0.0

    def __call__(self) -> float:
        return self.now_seconds

    def advance(self, ms: float) -> None:
        self.now_seconds += ms / 1000


def taking(clock: FakeClock, ms: float, step):
    """Wrap a fake's method so the call takes `ms` on the fake clock."""

    async def timed(*args, **kwargs):
        clock.advance(ms)
        return await step(*args, **kwargs)

    return timed


def slow_pipeline(candidates, clock: FakeClock) -> RAGPipeline:
    parser = QueryParser(load_titles=_no_catalogue)
    embedding, vector_store = FakeEmbedding(), FakeVectorStore(candidates)
    dedup, llm = FakeDeduplication(owned_titles=set()), FakeLLM()
    parser.parse = taking(clock, 2, parser.parse)
    embedding.embed_query = taking(clock, 30, embedding.embed_query)
    vector_store.top_k = taking(clock, 50, vector_store.top_k)
    dedup.filter_owned = taking(clock, 10, dedup.filter_owned)
    llm.rank = taking(clock, 2000, llm.rank)
    return RAGPipeline(embedding, vector_store, dedup, llm, parser=parser)


def timing_record(caplog):
    [record] = [r for r in caplog.records if r.getMessage() == "recommend.timings"]
    return record


async def test_pipeline_times_and_logs_every_stage(candidates, caplog):
    clock = FakeClock()
    timings = StageTimings(clock=clock)

    with caplog.at_level(logging.INFO, logger="gamegpt.latency"):
        await slow_pipeline(candidates, clock).recommend(DEV_USER, "cozy", timings=timings)

    record = timing_record(caplog)
    assert (record.parse_ms, record.embed_ms, record.retrieve_ms) == (2.0, 30.0, 50.0)
    assert (record.filter_ms, record.rank_ms) == (10.0, 2000.0)
    assert record.total_ms == 2092.0
    assert record.failed_stage is None


async def test_pipeline_logs_how_far_it_got_when_a_stage_fails(candidates, caplog):
    clock = FakeClock()
    pipeline = slow_pipeline(candidates, clock)

    async def llm_down(query, candidates, n=3):
        clock.advance(8000)
        raise TimeoutError("LLM took too long")

    pipeline.llm.rank = llm_down

    with caplog.at_level(logging.INFO, logger="gamegpt.latency"):
        with pytest.raises(TimeoutError):
            await pipeline.recommend(DEV_USER, "cozy", timings=StageTimings(clock=clock))

    record = timing_record(caplog)
    assert record.failed_stage == "rank"
    assert record.rank_ms == 8000.0
    assert record.filter_ms == 10.0


async def test_pipeline_times_itself_when_not_handed_a_timer(candidates, caplog):
    with caplog.at_level(logging.INFO, logger="gamegpt.latency"):
        await slow_pipeline(candidates, FakeClock()).recommend(DEV_USER, "cozy")

    assert timing_record(caplog).total_ms is not None
