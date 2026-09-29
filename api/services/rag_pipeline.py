"""RAGPipeline — orchestrates the five blocks into one recommend() call.

SysML block: RAG Pipeline. embed → top-k → drop owned → LLM rank. Persistence
of the query and its recommendations is the router's job (Agent C), not the
pipeline's — the pipeline stays pure so it is trivial to unit-test.
"""

from __future__ import annotations

from uuid import UUID

from api.models import Recommendation
from api.services.deduplication import DeduplicationService
from api.services.embedding import EmbeddingService
from api.services.llm import LLMService
from api.services.vector_store import VectorStore


class RAGPipeline:
    def __init__(
        self,
        embedding: EmbeddingService,
        vector_store: VectorStore,
        deduplication: DeduplicationService,
        llm: LLMService,
        *,
        k: int = 20,
        n: int = 3,
    ) -> None:
        self.embedding = embedding
        self.vector_store = vector_store
        self.deduplication = deduplication
        self.llm = llm
        self.k = k
        self.n = n

    async def recommend(self, user_id: UUID, query: str) -> list[Recommendation]:
        """Run the full retrieval→dedup→rank chain and return `n` results."""
        embedding = await self.embedding.embed_query(query)
        candidates = await self.vector_store.top_k(embedding, k=self.k)
        candidates = await self.deduplication.filter_owned(user_id, candidates)
        return await self.llm.rank(query, candidates, n=self.n)
