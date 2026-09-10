"""RAGPipeline orchestration tests with fully faked collaborators."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from api.models import GameCandidate, Recommendation
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

    async def top_k(self, embedding, k: int = 20):
        self.k_seen = k
        return self._candidates[:k]


class FakeDeduplication:
    def __init__(self, owned_titles: set[str]):
        self._owned = owned_titles

    async def filter_owned(self, user_id, candidates):
        return [c for c in candidates if c.title not in self._owned]


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
    pipeline = RAGPipeline(embedding, vector_store, dedup, llm, k=20, n=3)

    recs = await pipeline.recommend(DEV_USER, "a chill game for a podcast night")

    assert len(recs) == 3
    assert [r.rank for r in recs] == [1, 2, 3]
    assert all(r.reason.strip() for r in recs)
    assert embedding.calls == ["a chill game for a podcast night"]
    assert vector_store.k_seen == 20


async def test_pipeline_excludes_owned_games(candidates):
    owned = {"Stardew Valley"}  # the top candidate is owned
    embedding = FakeEmbedding()
    vector_store = FakeVectorStore(candidates)
    dedup = FakeDeduplication(owned_titles=owned)
    llm = FakeLLM()
    pipeline = RAGPipeline(embedding, vector_store, dedup, llm, k=20, n=3)

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
    pipeline = RAGPipeline(embedding, vector_store, dedup, llm, k=20, n=3)

    recs = await pipeline.recommend(DEV_USER, "relaxing game")

    assert len(recs) == 3
    assert all(r.reason.strip() for r in recs)
