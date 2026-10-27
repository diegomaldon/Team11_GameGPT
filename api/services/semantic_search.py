"""SemanticSearchService — the retrieval half of the pipeline on its own (TM11-42, REQ011).

Embeds the query and asks VectorStore for the k nearest catalogue games that
pass the platform and genre filters (TM11-43): the same two steps
RAGPipeline.recommend() starts with, without dropping owned games or calling
the LLM. That makes retrieval queryable by itself, so it can
be tested, timed and tuned apart from ranking.

Not a SysML block: it composes two of them (Embedding, Vector Store).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from api.models import GameCandidate, SemanticSearchResult
from api.services.embedding import EmbeddingService
from api.services.vector_store import NO_FILTERS, SearchFilters, VectorStore


@dataclass
class SearchOutcome:
    results: list[SemanticSearchResult]
    model: str
    took_ms: float


class SemanticSearchService:
    def __init__(
        self,
        embedding: EmbeddingService | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.embedding = embedding or EmbeddingService()
        # Search with the model the query was embedded with. A vector from one
        # model compared against another's means nothing.
        self.vector_store = vector_store or VectorStore(model=self.embedding.model_name)

    async def search(
        self, query: str, k: int, filters: SearchFilters = NO_FILTERS,
    ) -> SearchOutcome:
        """Return up to `k` games closest to `query` that pass `filters`, ranked 1..n."""
        started = time.perf_counter()
        # embed_documents, not embed_query: if the model can't load it raises
        # EmbeddingModelError (a 503) instead of quietly searching with a stub
        # vector under the real model's name.
        vector = (await self.embedding.embed_documents([query]))[0].vector
        candidates = await self.vector_store.top_k(vector, k=k, filters=filters)
        took_ms = (time.perf_counter() - started) * 1000
        return SearchOutcome(
            results=rank_candidates(candidates),
            model=self.vector_store.model,
            took_ms=round(took_ms, 2),
        )


def rank_candidates(candidates: list[GameCandidate]) -> list[SemanticSearchResult]:
    """Number candidates best first.

    VectorStore already orders by distance; the sort is stable, so this only
    matters if a store ever returns them out of order, and ties keep its order.
    """
    ordered = sorted(candidates, key=lambda c: c.similarity or 0.0, reverse=True)
    return [
        SemanticSearchResult(
            rank=rank,
            game_id=c.game_id,
            title=c.title,
            similarity=round(c.similarity or 0.0, 4),
            genres=c.genres,
            steam_appid=c.steam_appid,
            review_score=c.review_score,
        )
        for rank, c in enumerate(ordered, start=1)
    ]
