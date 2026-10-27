"""VectorStore and DeduplicationService on both database shapes (TM11-40).

The connection is faked, so these run offline. They pin the SQL the hosted
path sends, because the partial HNSW index only serves a query that repeats
its cast and model filter exactly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from api.db import schema
from api.models import GameCandidate
from api.services import deduplication, vector_store
from api.services.deduplication import DeduplicationService
from api.services.vector_store import VectorStore, hosted_top_k_sql

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params=None):
        self.executed.append((query, params))

    async def fetchall(self):
        return self.rows

    async def fetchone(self):
        return self.rows[0]


def fake_connection(cursor: FakeCursor):
    class Conn:
        def cursor(self):
            return cursor

    @asynccontextmanager
    async def connection():
        yield Conn()

    return connection


def make_candidate(title: str) -> GameCandidate:
    return GameCandidate(game_id=uuid4(), title=title)


def rendered(query) -> str:
    return query if isinstance(query, str) else query.as_string(None)


# ── the hosted query ────────────────────────────────────────────────────────


def test_hosted_sql_matches_the_partial_index_definition():
    text = hosted_top_k_sql(MODEL, 384).as_string(None)

    assert f"where e.model = '{MODEL}'" in text
    assert text.count("e.embedding::extensions.vector(384) OPERATOR(extensions.<=>) %(vec)s::extensions.vector(384)") == 2
    assert "from public.game_embeddings e" in text
    assert text.rstrip().endswith("limit %(k)s")
    assert "%s" not in text  # positional placeholders would need the vector bound twice


def test_hosted_sql_quotes_the_model_name():
    text = hosted_top_k_sql("o'reilly/model", 384).as_string(None)
    assert "'o''reilly/model'" in text


def test_the_store_defaults_to_the_configured_model():
    store = VectorStore()
    assert store.model == MODEL
    assert store.dimensions == 384


# ── top_k on each shape ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hosted_top_k_reads_game_embeddings(monkeypatch):
    game_id = uuid4()
    cursor = FakeCursor([
        (game_id, "Portal 2", "Puzzles with portals.", ["Puzzle"], ["co-op"],
         ["Valve", "Valve Seattle"], 98, 620, 0.25),
    ])
    monkeypatch.setattr(vector_store, "connection", fake_connection(cursor))

    async def hosted():
        return "hosted"

    monkeypatch.setattr(vector_store, "catalogue_shape", hosted)

    [candidate] = await VectorStore().top_k([0.1, 0.2], k=5)

    query, params = cursor.executed[-1]
    assert "public.game_embeddings" in rendered(query)
    assert params == {"vec": "[0.1,0.2]", "k": 5}
    assert candidate.game_id == game_id
    assert candidate.developer == "Valve, Valve Seattle"
    assert candidate.review_score == pytest.approx(0.98)
    assert candidate.similarity == pytest.approx(0.75)


@pytest.mark.asyncio
@pytest.mark.parametrize("k, ef_search", [(5, "40"), (40, "40"), (41, "41"), (50, "50")])
async def test_hosted_top_k_widens_the_hnsw_search_to_k(monkeypatch, k, ef_search):
    # The HNSW candidate list (ef_search, default 40) is widened to at least k.
    cursor = FakeCursor([])
    monkeypatch.setattr(vector_store, "connection", fake_connection(cursor))

    async def hosted():
        return "hosted"

    monkeypatch.setattr(vector_store, "catalogue_shape", hosted)

    await VectorStore().top_k([0.1, 0.2], k=k)

    (set_query, set_params), (search_query, _) = cursor.executed
    assert "set_config('hnsw.ef_search', %s, true)" in rendered(set_query)
    assert set_params == (ef_search,)
    assert "public.game_embeddings" in rendered(search_query)


@pytest.mark.asyncio
async def test_legacy_top_k_reads_games_embedding(monkeypatch):
    cursor = FakeCursor([
        (uuid4(), "Celeste", None, None, None, "Maddy Makes Games", 0.95, 504230, 1.3),
    ])
    monkeypatch.setattr(vector_store, "connection", fake_connection(cursor))

    async def legacy():
        return "legacy"

    monkeypatch.setattr(vector_store, "catalogue_shape", legacy)

    [candidate] = await VectorStore().top_k([0.0], k=1)

    (probes_query, probes_params), (query, _) = cursor.executed
    # Every IVFFlat list is probed: with lists = 100 over ~170 games, the
    # default of one list can return no rows at all.
    assert "set_config('ivfflat.probes', %s, true)" in rendered(probes_query)
    assert probes_params == ("100",)
    assert "from games" in rendered(query)
    assert "game_embeddings" not in rendered(query)
    assert candidate.genres == [] and candidate.tags == []
    assert candidate.review_score == 0.95
    assert candidate.similarity == 0.0  # distance > 1 is clamped


# ── dedup on the hosted shape ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hosted_dedup_drops_owned_games_by_game_id(monkeypatch):
    owned, other = make_candidate("Hades"), make_candidate("Hades II")
    cursor = FakeCursor([(owned.game_id, "STEAM")])
    monkeypatch.setattr(deduplication, "connection", fake_connection(cursor))

    async def hosted():
        return "hosted"

    monkeypatch.setattr(deduplication, "catalogue_shape", hosted)
    user_id = uuid4()

    kept = await DeduplicationService().filter_owned(user_id, [owned, other])

    assert kept == [other]  # a similar title is not mistaken for the owned game
    assert cursor.executed[0][1][0] == user_id


# ── shape detection ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shape_is_detected_once_per_database(monkeypatch):
    cursor = FakeCursor([(True,)])
    monkeypatch.setattr(schema, "connection", fake_connection(cursor))
    schema.reset_shape_cache()

    assert await schema.catalogue_shape() == "hosted"
    assert await schema.catalogue_shape() == "hosted"
    assert len(cursor.executed) == 1
    schema.reset_shape_cache()
