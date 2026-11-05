"""HybridRetriever (TM11-65, REQ011, REQ015).

One group per acceptance criterion. The vector store is faked, so these run
offline; scripts/eval_hybrid_retrieval.py measures the same code on the real
model and catalogue.
"""

from __future__ import annotations

import random
from uuid import UUID, uuid4

import pytest

from api.models import GameCandidate
from api.services.hybrid_retrieval import (
    DEFAULT_METADATA_WEIGHT,
    DEFAULT_POOL_SIZE,
    DEFAULT_SEMANTIC_WEIGHT,
    HybridRetriever,
    RetrievalWeights,
    merge_and_score,
    metadata_filters,
    metadata_match,
)
from api.services.query_parser import ParsedQuery, ReferenceTitle
from api.services.vector_store import SearchFilters


def game(title, similarity, *, genres=(), tags=(), platforms=("steam",), game_id=None):
    return GameCandidate(
        game_id=game_id or uuid4(), title=title, similarity=similarity,
        genres=list(genres), tags=list(tags), platforms=list(platforms),
    )


def titles(scored) -> list[str]:
    return [s.candidate.title for s in scored]


class FakeStore:
    """Answers top_k from a fixed catalogue, filtering like the real SQL does."""

    def __init__(self, catalogue):
        self.catalogue = sorted(catalogue, key=lambda c: -c.similarity)
        self.calls: list[tuple[int, SearchFilters | None]] = []

    async def top_k(self, embedding, k=20, filters=None):
        self.calls.append((k, filters))
        rows = self.catalogue
        if filters and filters.genres:
            wanted = {g.lower() for g in filters.genres}
            rows = [c for c in rows if wanted & {g.lower() for g in c.genres}]
        if filters and filters.platforms:
            rows = [c for c in rows if set(filters.platforms) & set(c.platforms)]
        return rows[:k]


# ───── AC: semantic and metadata-filtered results merged, with documented weighting ─────


def test_a_strict_match_outside_the_semantic_pool_is_merged_in():
    close = [game(f"Near {i}", 0.9 - i * 0.01) for i in range(5)]
    roguelike = game("Hades", 0.4, genres=["Roguelike"])
    parsed = ParsedQuery(genres=("Roguelike",))

    ranked = merge_and_score([close, [roguelike]], parsed)

    assert "Hades" in titles(ranked)


def test_a_game_found_by_both_searches_appears_once():
    both = game("Hades", 0.8, genres=["Roguelike"])
    ranked = merge_and_score([[both], [both]], ParsedQuery(genres=("Roguelike",)))
    assert titles(ranked) == ["Hades"]


def test_score_is_the_documented_weighted_sum():
    weights = RetrievalWeights()
    assert weights.semantic == DEFAULT_SEMANTIC_WEIGHT
    assert weights.metadata == DEFAULT_METADATA_WEIGHT
    parsed = ParsedQuery(genres=("Roguelike",), moods=("tense", "dark"))
    candidate = game("Darkest Dungeon", 0.5, genres=["Roguelike"], tags=["tense"])

    [scored] = merge_and_score([[candidate]], parsed, weights)

    # genre met (1.0), half the moods met (0.5) -> match 0.75
    assert scored.match == pytest.approx(0.75)
    assert scored.score == pytest.approx(0.7 * 0.5 + 0.3 * 0.75)


def test_a_signal_match_can_outrank_a_closer_game():
    plain = game("Close but off-genre", 0.62, genres=["Puzzle"])
    match = game("A real roguelike", 0.55, genres=["Roguelike"])
    ranked = merge_and_score([[plain, match]], ParsedQuery(genres=("Roguelike",)))
    assert titles(ranked) == ["A real roguelike", "Close but off-genre"]


def test_no_signals_rank_exactly_as_semantic_search_did():
    games = [game(f"G{i}", s) for i, s in enumerate([0.9, 0.7, 0.8, 0.1])]
    ranked = merge_and_score([games], ParsedQuery())
    assert titles(ranked) == ["G0", "G2", "G1", "G3"]
    assert [s.score for s in ranked] == [0.9, 0.8, 0.7, 0.1]


@pytest.mark.parametrize("parsed, candidate, expected", [
    (ParsedQuery(genres=("RPG", "Strategy")), game("x", 0.5, genres=["strategy"]), 1.0),
    (ParsedQuery(genres=("RPG",)), game("x", 0.5, genres=["Puzzle"]), 0.0),
    (ParsedQuery(moods=("cozy", "relaxing")), game("x", 0.5, tags=["cozy"]), 0.5),
    (ParsedQuery(platforms=("xbox",)), game("x", 0.5, platforms=["steam", "xbox"]), 1.0),
    (ParsedQuery(platforms=("epic",)), game("x", 0.5, platforms=["steam"]), 0.0),
    (ParsedQuery(), game("x", 0.5), None),
])
def test_metadata_match_per_signal_kind(parsed, candidate, expected):
    assert metadata_match(candidate, parsed) == expected


def test_moods_only_score_they_are_not_a_database_filter():
    assert metadata_filters(ParsedQuery(moods=("cozy",))) is None
    assert metadata_filters(ParsedQuery(genres=("RPG",), platforms=("xbox",))) == SearchFilters(
        platforms=("xbox",), genres=("RPG",)
    )


@pytest.mark.parametrize("semantic, metadata", [(-0.1, 0.5), (0.0, 0.0)])
def test_weights_must_be_non_negative_and_not_both_zero(semantic, metadata):
    with pytest.raises(ValueError):
        RetrievalWeights(semantic=semantic, metadata=metadata)


# ───── Ruled-out and named games ─────


def test_excluded_genres_and_moods_are_removed():
    parsed = ParsedQuery(excluded_genres=("Shooter",), excluded_moods=("tense",))
    games = [game("Shooter", 0.9, genres=["Shooter"]), game("Scary", 0.8, tags=["tense"]),
             game("Fine", 0.5)]
    assert titles(merge_and_score([games], parsed)) == ["Fine"]


def test_a_game_only_on_an_excluded_platform_is_removed_but_one_also_elsewhere_stays():
    parsed = ParsedQuery(excluded_platforms=("xbox",))
    games = [game("Xbox only", 0.9, platforms=["xbox"]),
             game("Xbox and Steam", 0.8, platforms=["xbox", "steam"])]
    assert titles(merge_and_score([games], parsed)) == ["Xbox and Steam"]


def test_the_named_game_and_ruled_out_games_are_never_answers():
    hades, celeste, other = uuid4(), uuid4(), uuid4()
    parsed = ParsedQuery(
        reference_titles=(ReferenceTitle(hades, "Hades", "hades"),),
        excluded_reference_titles=(ReferenceTitle(celeste, "Celeste", "celeste"),),
    )
    games = [game("Hades", 0.95, game_id=hades), game("Celeste", 0.9, game_id=celeste),
             game("Dead Cells", 0.85, game_id=other)]
    assert titles(merge_and_score([games], parsed)) == ["Dead Cells"]


# ───── AC: candidate count tuned and recorded ─────


@pytest.mark.asyncio
async def test_retrieve_returns_at_most_k():
    store = FakeStore([game(f"G{i}", 1 - i / 100) for i in range(80)])
    found = await HybridRetriever(store).retrieve([0.0], ParsedQuery(), k=20)
    assert len(found) == 20


@pytest.mark.asyncio
async def test_each_search_pulls_the_tuned_pool_size():
    store = FakeStore([game("G", 0.5, genres=["RPG"])])
    await HybridRetriever(store).retrieve([0.0], ParsedQuery(genres=("RPG",)), k=20)
    assert [k for k, _ in store.calls] == [DEFAULT_POOL_SIZE, DEFAULT_POOL_SIZE]
    assert store.calls[0][1] is None
    assert store.calls[1][1] == SearchFilters(genres=("RPG",))


@pytest.mark.asyncio
async def test_the_pool_is_never_smaller_than_k():
    store = FakeStore([game("G", 0.5)])
    await HybridRetriever(store, pool_size=10).retrieve([0.0], ParsedQuery(), k=30)
    assert store.calls == [(30, None)]


@pytest.mark.asyncio
async def test_a_query_without_genres_or_platforms_runs_one_search():
    store = FakeStore([game("G", 0.5, tags=["cozy"])])
    await HybridRetriever(store).retrieve([0.0], ParsedQuery(moods=("cozy",)), k=20)
    assert len(store.calls) == 1


def test_pool_size_must_be_positive():
    with pytest.raises(ValueError):
        HybridRetriever(FakeStore([]), pool_size=0)


# ───── AC: deterministic given the same query and corpus ─────


def _catalogue():
    rng = random.Random(7)
    genres = ["RPG", "Roguelike", "Puzzle", "Shooter"]
    return [
        game(f"Game {i:02d}", round(rng.uniform(0.2, 0.9), 2), genres=[rng.choice(genres)],
             tags=rng.sample(["cozy", "tense", "dark", "relaxing"], 2),
             game_id=UUID(int=i + 1))
        for i in range(40)
    ]


def test_same_inputs_give_the_same_list_whatever_order_rows_arrive_in():
    parsed = ParsedQuery(genres=("Roguelike",), moods=("tense",))
    semantic = _catalogue()
    filtered = [c for c in semantic if "Roguelike" in c.genres]
    expected = titles(merge_and_score([semantic, filtered], parsed))

    rng = random.Random(1)
    for _ in range(20):
        a, b = semantic[:], filtered[:]
        rng.shuffle(a)
        rng.shuffle(b)
        legs = [a, b] if rng.random() < 0.5 else [b, a]
        assert titles(merge_and_score(legs, parsed)) == expected


def test_ties_break_on_similarity_then_title_then_id():
    same = dict(genres=["RPG"])
    games = [
        game("B", 0.5, **same, game_id=UUID(int=2)),
        game("A", 0.5, **same, game_id=UUID(int=3)),
        game("A", 0.5, **same, game_id=UUID(int=1)),
    ]
    ranked = merge_and_score([games], ParsedQuery(genres=("RPG",)))
    assert [(s.candidate.title, s.candidate.game_id.int) for s in ranked] == [
        ("A", 1), ("A", 3), ("B", 2),
    ]


@pytest.mark.asyncio
async def test_retrieve_twice_gives_the_same_candidates():
    store = FakeStore(_catalogue())
    retriever = HybridRetriever(store)
    parsed = ParsedQuery(genres=("Puzzle",), moods=("cozy",))
    first = await retriever.retrieve([0.0], parsed, k=20)
    second = await retriever.retrieve([0.0], parsed, k=20)
    assert [c.game_id for c in first] == [c.game_id for c in second]


# ───── The pipeline uses it ─────


@pytest.mark.asyncio
async def test_the_pipeline_retrieves_with_the_parsed_signals():
    from api.services.rag_pipeline import RAGPipeline

    parsed = ParsedQuery(genres=("Roguelike",))

    class Parser:
        async def parse(self, query):
            return parsed

    class Stub:
        async def embed_query(self, text):
            return [0.0]

        async def filter_owned(self, user_id, candidates):
            return candidates

        async def rank(self, query, candidates, n=3):
            self.seen = candidates
            return []

    store = FakeStore([game("Off genre", 0.6), game("Hades", 0.5, genres=["Roguelike"])])
    stub = Stub()
    await RAGPipeline(stub, store, stub, stub, k=1, parser=Parser()).recommend(
        UUID(int=1), "a roguelike"
    )

    assert store.calls[1][1] == SearchFilters(genres=("Roguelike",))
    # Hades: 0.7 * 0.5 + 0.3 * 1.0 = 0.65 beats the closer off-genre game's 0.7 * 0.6 = 0.42.
    assert [c.title for c in stub.seen] == ["Hades"]
