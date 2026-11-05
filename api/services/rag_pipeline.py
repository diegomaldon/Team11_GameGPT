"""RAGPipeline — orchestrates the five blocks into one recommend() call.

SysML block: RAG Pipeline. parse → embed → retrieve → drop owned → LLM rank. Persistence
of the query and its recommendations is the router's job (Agent C), not the
pipeline's — the pipeline stays pure so it is trivial to unit-test.

The parse step (TM11-62) reads genre, mood, platform and reference-title
signals out of the query and logs them. Retrieval (TM11-65) merges a plain
semantic search with one filtered to those signals and scores the union, so
the candidates the LLM sees match what was asked for, not just how it reads.
"""

from __future__ import annotations

from uuid import UUID

from api.models import Recommendation
from api.services.deduplication import DeduplicationService
from api.services.embedding import EmbeddingService
from api.services.hybrid_retrieval import HybridRetriever
from api.services.llm import LLMService
from api.services.query_parser import QueryParser
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
        parser: QueryParser | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        self.embedding = embedding
        self.vector_store = vector_store
        self.deduplication = deduplication
        self.llm = llm
        self.k = k
        self.n = n
        self.parser = parser or QueryParser()
        self.retriever = retriever or HybridRetriever(vector_store)

    async def recommend(self, user_id: UUID, query: str) -> list[Recommendation]:
        """Run the full parse→retrieval→dedup→rank chain and return `n` results."""
        parsed = await self.parser.parse(query)
        embedding = await self.embedding.embed_query(query)
        candidates = await self.retriever.retrieve(embedding, parsed, k=self.k)
        candidates = await self.deduplication.filter_owned(user_id, candidates)
        return await self.llm.rank(query, candidates, n=self.n)
