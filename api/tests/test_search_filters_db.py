"""Metadata filters against a real catalogue (TM11-43).

Read-only, so it is safe on any DATABASE_URL, and it works on either shape. A
filtered search has to return exactly what the unfiltered ranking returns once
the non-matching games are struck out: the same games, in the same order, up
to k. Skips when no database is reachable.
"""

from __future__ import annotations

from collections import Counter

import psycopg
import pytest

from api.db import connection, has_db
from api.db.schema import catalogue_shape
from api.services.embedding import EMBEDDING_DIM
from api.services.vector_store import SearchFilters, VectorStore

pytestmark = pytest.mark.asyncio

# Any fixed non-zero vector gives a stable ranking. A zero vector has no
# cosine distance at all.
QUERY = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
EVERY_GAME = 1000
K = 5


async def full_ranking() -> list:
    """Every embedded game, closest first. Skips when there is nothing to search."""
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    try:
        games = await VectorStore().top_k(QUERY, k=EVERY_GAME)
    except psycopg.Error as exc:
        pytest.skip(f"DB not usable: {type(exc).__name__}")
    if not games:
        pytest.skip("the catalogue has no embeddings")
    return games


async def platforms_by_game() -> dict:
    if await catalogue_shape() == "legacy":
        # No platform column: every game in the 0001 slice came from Steam.
        query = "select id, array['steam'] from games where steam_appid is not null"
    else:
        query = ("select game_id, array(select lower(p::text) from unnest(available_platforms) p) "
                 "from public.games")
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query)
            return dict(await cur.fetchall())


def ids(games) -> list:
    return [g.game_id for g in games]


def has_genre(game, genre: str) -> bool:
    return genre.lower() in (g.lower() for g in game.genres)


def most_common_genre(games) -> str:
    return Counter(g for game in games for g in game.genres).most_common(1)[0][0]


async def test_a_genre_filter_keeps_the_similarity_order():
    ranking = await full_ranking()
    genre = most_common_genre(ranking)

    found = await VectorStore().top_k(QUERY, k=K, filters=SearchFilters(genres=(genre.upper(),)))

    expected = [g for g in ranking if has_genre(g, genre)][:K]
    assert found and all(has_genre(g, genre) for g in found)
    assert ids(found) == ids(expected)


async def test_platform_and_genre_filters_combine():
    ranking = await full_ranking()
    platforms = await platforms_by_game()
    genre = most_common_genre(ranking)

    found = await VectorStore().top_k(
        QUERY, k=K, filters=SearchFilters(platforms=("steam",), genres=(genre,)),
    )

    expected = [
        g for g in ranking
        if has_genre(g, genre) and "steam" in platforms.get(g.game_id, [])
    ][:K]
    assert ids(found) == ids(expected)


async def test_a_filter_nothing_matches_returns_no_games():
    await full_ranking()
    found = await VectorStore().top_k(QUERY, k=K, filters=SearchFilters(genres=("no such genre",)))
    assert found == []
