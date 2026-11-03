"""Query history against a real Postgres (TM11-64).

Saves through the same repository the recommend route uses, then reads it back
on a new connection, the way a user signing back in would. Writes rows, so like
test_seeded_demo_db.py it only runs on the local schema (CI's db-seeded job or
a database built with scripts/seed_demo.py), and deletes what it wrote. Skips
when DATABASE_URL is unset, unreachable or the hosted schema.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import psycopg
import pytest

from api.config import get_settings
from api.db import connection, has_db, repositories
from api.db.schema import catalogue_shape
from api.models import Recommendation

DEV_USER = UUID(get_settings().dev_user_id)


async def _fetch(sql: str, *params) -> list[tuple]:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


async def _execute(sql: str, *params) -> None:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
        await conn.commit()


@pytest.fixture(scope="module")
def catalogue_games() -> list[tuple[UUID, str]]:
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    try:
        shape = asyncio.run(catalogue_shape())
    except psycopg.Error as exc:
        pytest.skip(f"DB not usable: {type(exc).__name__}")
    if shape != "legacy":
        pytest.skip("writes rows, so it only runs on the local schema")
    games = asyncio.run(_fetch("select id, title from games order by title limit 3"))
    if len(games) < 3:
        pytest.skip("the catalogue is empty: run scripts/seed_demo.py")
    return games


@pytest.fixture
def saved_queries():
    """Query ids a test saved, deleted afterwards (results cascade)."""
    ids: list[UUID] = []
    yield ids
    for query_id in ids:
        asyncio.run(_execute("delete from queries where id = %s", str(query_id)))


def save(saved_queries: list[UUID], query: str, games: list[tuple[UUID, str]]) -> UUID:
    query_id = uuid4()
    saved_queries.append(query_id)
    recommendations = [
        Recommendation(rank=rank, game_id=game_id, title=title, reason=f"why {title}")
        for rank, (game_id, title) in enumerate(games, start=1)
    ]
    asyncio.run(repositories.save_query_history(
        query_id=query_id, user_id=DEV_USER, query=query, recommendations=recommendations,
    ))
    return query_id


def history(user_id: UUID) -> list:
    return asyncio.run(repositories.list_query_history(user_id, limit=50))



def test_a_saved_query_reads_back_with_its_ranked_results(catalogue_games, saved_queries):
    query_id = save(saved_queries, "tm11-64 cozy farming", catalogue_games)

    entry = next(e for e in history(DEV_USER) if e.query_id == query_id)

    assert entry.query == "tm11-64 cozy farming"
    assert entry.created_at is not None
    assert [(r.rank, r.game_id, r.title) for r in entry.recommendations] == [
        (rank, game_id, title) for rank, (game_id, title) in enumerate(catalogue_games, start=1)
    ]


def test_history_is_newest_first(catalogue_games, saved_queries):
    first = save(saved_queries, "tm11-64 first", catalogue_games)
    second = save(saved_queries, "tm11-64 second", catalogue_games)

    ids = [e.query_id for e in history(DEV_USER)]

    assert ids.index(second) < ids.index(first)


def test_another_user_does_not_see_it(catalogue_games, saved_queries):
    query_id = save(saved_queries, "tm11-64 private", catalogue_games)

    assert query_id not in {e.query_id for e in history(uuid4())}


def test_titles_come_from_the_catalogue_by_game_id(catalogue_games, saved_queries):
    query_id = save(saved_queries, "tm11-64 by id", catalogue_games)
    asyncio.run(_execute(
        "update recommendations set title = 'stale copy' where query_id = %s", str(query_id),
    ))

    entry = next(e for e in history(DEV_USER) if e.query_id == query_id)

    assert [r.title for r in entry.recommendations] == [title for _, title in catalogue_games]
