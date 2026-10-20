"""The seeded demo account, read back through the real API (TM11-88).

Runs against a real Postgres: CI's db-seeded job, or a local database built
with `python scripts/seed_demo.py`. The module seeds first (idempotent, so it is
safe on a dev database) and skips when DATABASE_URL is unset, the database is
unreachable, or it has the hosted Supabase schema.

Every test goes through the routes and services the web app uses, so a schema
or seed change that breaks the demo fails here before it fails on stage.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import connection, has_db
from api.main import create_app
from api.models import GameCandidate
from api.services.deduplication import DeduplicationService

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"


def _load_seed_demo():
    spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = module
    spec.loader.exec_module(module)
    return module


seed_demo = _load_seed_demo()


@pytest.fixture(autouse=True)
def offline_services(monkeypatch):
    """Keyless stub embedding and LLM, so the run needs no network or torch."""
    monkeypatch.setenv("EMBEDDING_STUB", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def demo_user() -> UUID:
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    try:
        exit_code = seed_demo.main([])
    except psycopg.Error as exc:
        pytest.skip(f"DB not usable: {exc}")
    if exit_code == 2:
        pytest.skip("database has the hosted Supabase schema, not the local slice")
    assert exit_code == 0, "seed_demo did not produce a complete demo account"
    return UUID(get_settings().dev_user_id)


async def _fetch(sql: str, *params) -> list[tuple]:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


def test_check_passes_on_the_seeded_database(demo_user):
    assert seed_demo.main(["--check"]) == 0


def test_a_second_seed_adds_no_rows(demo_user):
    before = asyncio.run(_counts(demo_user))
    assert seed_demo.main([]) == 0
    assert asyncio.run(_counts(demo_user)) == before


async def _counts(user_id: UUID) -> seed_demo.SeedSummary:
    async with connection() as conn:
        async with conn.cursor() as cur:
            return await seed_demo.summarise_demo_account(cur, user_id)


def test_the_user_has_a_linked_steam_account(demo_user):
    rows = asyncio.run(_fetch(
        "select platform, external_id from platform_accounts where user_id = %s",
        str(demo_user),
    ))
    assert ("steam", seed_demo.DEMO_STEAM_ID) in rows


def test_get_library_returns_the_seeded_library_most_played_first(demo_user):
    resp = TestClient(create_app()).get("/api/library")

    assert resp.status_code == 200
    items = resp.json()["items"]
    titles = [i["title"] for i in items]
    for owned in seed_demo.DEMO_LIBRARY:
        assert owned.title in titles
    playtimes = [i["playtime_minutes"] for i in items]
    assert playtimes == sorted(playtimes, reverse=True)
    assert titles[0] == "Stardew Valley"


def test_every_library_game_is_linked_to_a_catalogue_row(demo_user):
    rows = asyncio.run(_fetch(
        "select o.title, g.title from owned_games o join games g on g.id = o.game_id "
        "where o.user_id = %s",
        str(demo_user),
    ))
    assert {owned for owned, _ in rows} >= {t.title for t in seed_demo.DEMO_LIBRARY}
    assert all(owned == catalogue for owned, catalogue in rows)


def test_dedup_drops_the_seeded_library_from_candidates(demo_user):
    owned = seed_demo.DEMO_LIBRARY[0]
    fresh = seed_demo.DEMO_QUERIES[0].recommendations[0]
    candidates = [
        GameCandidate(game_id=UUID(int=1), title=owned.title, steam_appid=owned.steam_appid),
        GameCandidate(game_id=UUID(int=2), title=fresh.title, steam_appid=fresh.steam_appid),
    ]

    kept = asyncio.run(DeduplicationService().filter_owned(demo_user, candidates))

    assert [c.title for c in kept] == [fresh.title]


def test_seeded_queries_have_ranked_recommendations_and_feedback(demo_user):
    rows = asyncio.run(_fetch(
        "select q.text, r.rank, r.title, f.vote "
        "from queries q join recommendations r on r.query_id = q.id "
        "left join recommendation_feedback f on f.query_id = q.id and f.rank = r.rank "
        "where q.id = any(%s::uuid[])",
        [str(q.query_id) for q in seed_demo.DEMO_QUERIES],
    ))
    by_query: dict[str, dict[int, tuple[str, str | None]]] = {}
    for text, rank, title, vote in rows:
        by_query.setdefault(text, {})[rank] = (title, vote)

    for q in seed_demo.DEMO_QUERIES:
        ranked = by_query[q.text]
        assert [ranked[r][0] for r in sorted(ranked)] == [r.title for r in q.recommendations]
        assert {r: ranked[r][1] for r, _ in q.votes} == dict(q.votes)


def test_recommend_and_feedback_work_end_to_end_for_the_demo_user(demo_user):
    has_vectors = asyncio.run(_fetch("select count(embedding) from games"))[0][0]
    if not has_vectors:
        pytest.skip("no embeddings yet: run EMBEDDING_STUB=1 python scripts/embed_games.py")

    client = TestClient(create_app())
    resp = client.post("/api/recommend", json={"query": "cozy relaxing farming game"})
    assert resp.status_code == 200
    body = resp.json()
    query_id = body["query_id"]
    try:
        recs = body["recommendations"]
        assert 1 <= len(recs) <= 5
        owned_titles = {t.title for t in seed_demo.DEMO_LIBRARY}
        assert not owned_titles & {r["title"] for r in recs}

        first = recs[0]
        vote = client.post("/api/feedback", json={
            "query_id": query_id, "game_id": first["game_id"],
            "title": first["title"], "rank": first["rank"], "vote": "up",
        })
        assert vote.status_code == 204
        stored = asyncio.run(_fetch(
            "select vote from recommendation_feedback where query_id = %s", query_id,
        ))
        assert stored == [("up",)]
    finally:
        # Keep a dev database's demo history as seeded; feedback cascades.
        asyncio.run(_delete_query(query_id))


async def _delete_query(query_id: str) -> None:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("delete from queries where id = %s", (query_id,))
        await conn.commit()
