"""RAGPipeline — orchestrates the five blocks into one recommend() call.

SysML block: RAG Pipeline. parse → embed → retrieve → drop owned → LLM rank. Persistence
of the query and its recommendations is the router's job (Agent C), not the
pipeline's — the pipeline stays pure so it is trivial to unit-test.

The parse step (TM11-62) reads genre, mood, platform and reference-title
signals out of the query and logs them. Retrieval (TM11-65) merges a plain
semantic search with one filtered to those signals and scores the union, so
the candidates the LLM sees match what was asked for, not just how it reads.

Owned games are dropped before the LLM ranks anything (TM11-66, REQ007): the
model only ever sees games the user doesn't own, so it can't pick one. When
that leaves fewer than `n`, retrieval runs once more, deeper (`refill_k`), and
only the games the first pass hadn't checked go back through the ownership
filter. If every match is still owned, the pipeline skips the LLM and returns
an `all_owned` notice the client can show, never a bare empty list.

Each stage is timed (TM11-68, REQ040) and logged as one `recommend.timings` line,
including when a stage fails, so the line shows how far the request got. A
refill adds to the retrieve and filter times rather than replacing them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from api.models import GameCandidate, Recommendation, RecommendNotice
from api.observability.stage_timings import TIMING_LOG_MESSAGE, StageTimings
from api.services.deduplication import DeduplicationService
from api.services.embedding import EmbeddingService
from api.services.hybrid_retrieval import HybridRetriever
from api.services.llm import LLMService
from api.services.query_parser import ParsedQuery, QueryParser
from api.services.vector_store import VectorStore

log = logging.getLogger("gamegpt.latency")

# How deep the one refill goes when the user owns most of the first k. A tenth
# of the 1000-game catalogue: deep enough to get past a big library, and still
# one search (TM11-65's pool grows to match, so both legs fetch this many).
DEFAULT_REFILL_K = 100

ALL_OWNED_NOTICE = RecommendNotice(
    code="all_owned",
    message=(
        "You already own every game that matches this search. "
        "Try describing it differently or widening the genre."
    ),
)


@dataclass(frozen=True)
class RecommendOutcome:
    """What one recommend call produced: the ranked results and, if short, why."""

    recommendations: list[Recommendation]
    notice: RecommendNotice | None = None


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
        refill_k: int = DEFAULT_REFILL_K,
        parser: QueryParser | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        self.embedding = embedding
        self.vector_store = vector_store
        self.deduplication = deduplication
        self.llm = llm
        self.k = k
        self.n = n
        self.refill_k = refill_k
        self.parser = parser or QueryParser()
        self.retriever = retriever or HybridRetriever(vector_store)

    async def recommend(
        self, user_id: UUID, query: str, *, timings: StageTimings | None = None
    ) -> list[Recommendation]:
        """Run the full parse→retrieval→dedup→rank chain and return up to `n` results.

        Pass `timings` to read the stage times afterwards (the router sends them back
        as Server-Timing). They are logged either way. Use recommend_outcome() to
        also get the notice explaining a short or empty list.
        """
        outcome = await self.recommend_outcome(user_id, query, timings=timings)
        return outcome.recommendations

    async def recommend_outcome(
        self, user_id: UUID, query: str, *, timings: StageTimings | None = None
    ) -> RecommendOutcome:
        """recommend(), plus the notice the client shows when every match is owned."""
        timings = timings or StageTimings()
        try:
            with timings.stage("parse"):
                parsed = await self.parser.parse(query)
            with timings.stage("embed"):
                embedding = await self.embedding.embed_query(query)
            with timings.stage("retrieve"):
                candidates = await self.retriever.retrieve(embedding, parsed, k=self.k)
            with timings.stage("filter"):
                unowned = await self.deduplication.filter_owned(user_id, candidates)

            if len(unowned) < self.n and self.refill_k > self.k:
                unowned = await self._refill(user_id, embedding, parsed, candidates, unowned, timings)

            if not unowned:
                log.info(
                    "recommend.all_owned",
                    extra={"candidates_checked": len(candidates), "refill_k": self.refill_k},
                )
                return RecommendOutcome(recommendations=[], notice=ALL_OWNED_NOTICE)

            with timings.stage("rank"):
                recommendations = await self.llm.rank(query, unowned, n=self.n)
            return RecommendOutcome(recommendations=recommendations)
        finally:
            log.info(TIMING_LOG_MESSAGE, extra=timings.log_fields())

    async def _refill(
        self,
        user_id: UUID,
        embedding: list[float],
        parsed: ParsedQuery,
        checked: list[GameCandidate],
        unowned: list[GameCandidate],
        timings: StageTimings,
    ) -> list[GameCandidate]:
        """The first pass's unowned games, then the unowned ones a deeper search adds.

        Games the first pass already checked keep their verdict and their place,
        so only the new ones cost an ownership lookup.
        """
        with timings.stage("retrieve"):
            deeper = await self.retriever.retrieve(embedding, parsed, k=self.refill_k)
        checked_ids = {c.game_id for c in checked}
        new = [c for c in deeper if c.game_id not in checked_ids]
        with timings.stage("filter"):
            refilled = unowned + await self.deduplication.filter_owned(user_id, new)
        log.info(
            "recommend.refill",
            extra={"first_pass_unowned": len(unowned), "after_refill": len(refilled)},
        )
        return refilled
