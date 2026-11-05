"""HybridRetriever: semantic and metadata-filtered candidates as one set (TM11-65, REQ011, REQ015).

The recommend pipeline used to take the top k by cosine similarity alone, so
"a roguelike on Steam" got whatever read most like the sentence, and a game
that matched both asks could sit just outside k. This retrieves with the
signals QueryParser read from the query (TM11-62):

  semantic   VectorStore.top_k with no filters: the closest games by meaning
  metadata   VectorStore.top_k filtered to the parsed genres and platforms, so
             strict matches are in the pool even when they read less alike

The two are merged by game_id and scored

  score = semantic_weight * similarity + metadata_weight * match

where `match` (0..1) is the share of the query's signal kinds the game meets:
any parsed genre in its genres, the share of parsed moods in its tags, any
parsed platform among its platforms. A query with no signals scores on
similarity alone, so it ranks exactly as plain semantic search did.

Before scoring, a game is dropped when it carries an excluded genre or mood,
is only on excluded platforms, or is a reference title. The player ruled the
first ones out, and a game they named ("like Hades") is the comparison, not
an answer. TM11-63's benchmark doesn't count it as a hit either.

Deterministic: the same query and catalogue give the same list. Ties break on
similarity, then title, then game_id, never on the order the database
returned rows in. The weights and pool size are tuned against the TM11-63
benchmark by scripts/eval_hybrid_retrieval.py; the numbers behind the defaults
are in artifacts/sprint9/tm11-65-hybrid-retrieval.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable, Sequence
from uuid import UUID

from api.models import GameCandidate
from api.services.query_parser import ParsedQuery
from api.services.vector_store import SearchFilters, VectorStore

# Tuned with scripts/eval_hybrid_retrieval.py; see the artifact named above.
DEFAULT_SEMANTIC_WEIGHT = 0.7
DEFAULT_METADATA_WEIGHT = 0.3
# Games fetched by each of the two searches before merging. Bigger pools find
# more strict matches but cost a little search time; the final cut is `k`.
DEFAULT_POOL_SIZE = 50


@dataclass(frozen=True)
class RetrievalWeights:
    semantic: float = DEFAULT_SEMANTIC_WEIGHT
    metadata: float = DEFAULT_METADATA_WEIGHT

    def __post_init__(self) -> None:
        if self.semantic < 0 or self.metadata < 0 or self.semantic + self.metadata <= 0:
            raise ValueError("weights must be non-negative and not both zero")


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: GameCandidate
    score: float
    match: float  # 0..1, share of the query's signal kinds this game meets


def _lower(values: Iterable[str]) -> set[str]:
    return {v.lower() for v in values}


def metadata_match(candidate: GameCandidate, parsed: ParsedQuery) -> float | None:
    """Share of the query's signal kinds the game meets, or None if the query has none."""
    parts: list[float] = []
    if parsed.genres:
        parts.append(1.0 if _lower(candidate.genres) & _lower(parsed.genres) else 0.0)
    if parsed.moods:
        tags = _lower(candidate.tags)
        parts.append(sum(m.lower() in tags for m in parsed.moods) / len(parsed.moods))
    if parsed.platforms:
        parts.append(1.0 if _lower(candidate.platforms) & _lower(parsed.platforms) else 0.0)
    return sum(parts) / len(parts) if parts else None


def is_ruled_out(candidate: GameCandidate, parsed: ParsedQuery) -> bool:
    """Whether the player excluded this game, or named it as the comparison."""
    named = {r.game_id for r in parsed.reference_titles}
    named |= {r.game_id for r in parsed.excluded_reference_titles}
    if candidate.game_id in named:
        return True
    if _lower(candidate.genres) & _lower(parsed.excluded_genres):
        return True
    if _lower(candidate.tags) & _lower(parsed.excluded_moods):
        return True
    platforms = _lower(candidate.platforms)
    # "Not on Xbox" rules out Xbox-only games; a game also on Steam still fits.
    return bool(platforms) and platforms <= _lower(parsed.excluded_platforms)


def merge_and_score(
    legs: Sequence[Sequence[GameCandidate]],
    parsed: ParsedQuery,
    weights: RetrievalWeights = RetrievalWeights(),
) -> list[ScoredCandidate]:
    """One list from every search's results, best first. Pure and deterministic."""
    by_id: dict[UUID, GameCandidate] = {}
    for leg in legs:
        for c in leg:
            seen = by_id.get(c.game_id)
            # The same game from both searches has the same similarity; keep one.
            if seen is None or (c.similarity or 0.0) > (seen.similarity or 0.0):
                by_id[c.game_id] = c

    total = weights.semantic + weights.metadata
    scored = []
    for c in by_id.values():
        if is_ruled_out(c, parsed):
            continue
        similarity = c.similarity or 0.0
        match = metadata_match(c, parsed)
        if match is None:
            score = similarity
            match = 0.0
        else:
            score = (weights.semantic * similarity + weights.metadata * match) / total
        scored.append(ScoredCandidate(c, round(score, 6), match))

    scored.sort(key=lambda s: (
        -s.score, -(s.candidate.similarity or 0.0), s.candidate.title, str(s.candidate.game_id),
    ))
    return scored


def metadata_filters(parsed: ParsedQuery) -> SearchFilters | None:
    """The filters for the metadata search, or None when the query names no genre or platform.

    Moods aren't a database filter: they're tags, and the tag vocabulary is
    looser than genres, so they only score.
    """
    if not parsed.genres and not parsed.platforms:
        return None
    return SearchFilters(platforms=tuple(parsed.platforms), genres=tuple(parsed.genres))


class HybridRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        *,
        weights: RetrievalWeights = RetrievalWeights(),
        pool_size: int = DEFAULT_POOL_SIZE,
    ) -> None:
        if pool_size < 1:
            raise ValueError("pool_size must be at least 1")
        self.vector_store = vector_store
        self.weights = weights
        self.pool_size = pool_size

    async def retrieve(
        self, embedding: list[float], parsed: ParsedQuery, k: int,
    ) -> list[GameCandidate]:
        """The `k` best candidates for the query, merged from both searches."""
        pool = max(self.pool_size, k)
        searches = [self.vector_store.top_k(embedding, k=pool)]
        filters = metadata_filters(parsed)
        if filters is not None:
            searches.append(self.vector_store.top_k(embedding, k=pool, filters=filters))
        # Concurrent: each search opens its own connection, so the second one
        # costs no extra wall time.
        legs = await asyncio.gather(*searches)
        return [s.candidate for s in merge_and_score(legs, parsed, self.weights)[:k]]
