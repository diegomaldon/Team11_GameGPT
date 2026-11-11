"""Query history: saving every recommend call and reading it back (TM11-64, REQ037, REQ038).

One group per acceptance criterion. The database is faked, so these run
offline; test_query_history_db.py reads the history back from a real Postgres.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import repositories
from api.main import create_app
from api.models import HistoryEntry, Recommendation
from api.routers import history as history_router
from api.routers import recommend as recommend_router
from api.services import query_history
from api.services.rag_pipeline import RecommendOutcome

USER = uuid4()
ASKED_AT = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def recommendation(rank: int, title: str, game_id: UUID | None = None) -> Recommendation:
    return Recommendation(rank=rank, game_id=game_id, title=title, reason=f"why {title}")


RESULTS = [
    recommendation(1, "Stardew Valley", uuid4()),
    recommendation(2, "Dinkum", uuid4()),
    recommendation(3, "Ooblets", uuid4()),
]


class FakeCursor:
    def __init__(self, rows=(), fail_on: str | None = None) -> None:
        self.rows = list(rows)
        self.fail_on = fail_on
        self.executed: list[tuple[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, query, params=None):
        self._record(query, params)

    async def executemany(self, query, params):
        self._record(query, list(params))

    async def fetchall(self):
        return self.rows

    def _record(self, query, params) -> None:
        text = query if isinstance(query, str) else query.as_string(None)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("connection to db.secret-host lost")
        self.executed.append((text, params))


class FakeDatabase:
    def __init__(self, shape: str, cursor: FakeCursor) -> None:
        self.shape = shape
        self.cursor = cursor
        self.commits = 0

    def install(self, monkeypatch) -> None:
        database = self

        class Conn:
            def cursor(self):
                return database.cursor

            async def commit(self):
                database.commits += 1

        @asynccontextmanager
        async def connection():
            yield Conn()

        async def catalogue_shape():
            return database.shape

        monkeypatch.setattr(repositories, "connection", connection)
        monkeypatch.setattr(repositories, "catalogue_shape", catalogue_shape)


def fake_db(monkeypatch, shape: str, **cursor_args) -> FakeDatabase:
    database = FakeDatabase(shape, FakeCursor(**cursor_args))
    database.install(monkeypatch)
    return database


async def save(results=RESULTS) -> UUID:
    query_id = uuid4()
    await repositories.save_query_history(
        query_id=query_id, user_id=USER, query="cozy farming game", recommendations=results,
    )
    return query_id


# AC: every query and its ranked results persisted with timestamps.

@pytest.mark.asyncio
async def test_hosted_save_writes_the_query_then_its_ranked_results(monkeypatch):
    db = fake_db(monkeypatch, "hosted")

    query_id = await save()

    (query_sql, query_params), (results_sql, results_params) = db.cursor.executed
    assert query_sql.startswith("insert into public.queries (query_id, user_id, query_text)")
    assert query_params == (str(query_id), str(USER), "cozy farming game")
    assert results_sql.startswith(
        "insert into public.recommendations (query_id, game_id, rank, explanation)"
    )
    assert results_params == [
        (str(query_id), str(r.game_id), r.rank, r.reason) for r in RESULTS
    ]


@pytest.mark.asyncio
async def test_legacy_save_writes_the_local_columns(monkeypatch):
    db = fake_db(monkeypatch, "legacy")

    query_id = await save()

    (query_sql, query_params), (results_sql, results_params) = db.cursor.executed
    assert query_sql.startswith("insert into queries (id, user_id, text)")
    assert query_params == (str(query_id), str(USER), "cozy farming game")
    assert results_sql.startswith(
        "insert into recommendations (query_id, game_id, rank, title, reason)"
    )
    assert results_params[0] == (str(query_id), str(RESULTS[0].game_id), 1,
                                 "Stardew Valley", "why Stardew Valley")


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["hosted", "legacy"])
async def test_timestamps_come_from_the_database_clock(monkeypatch, shape):
    # created_at / generated_at default to now() in both schemas. Setting them
    # from the app would let a slow or skewed server reorder the history.
    db = fake_db(monkeypatch, shape)

    await save()

    assert not any("created_at" in sql or "generated_at" in sql for sql, _ in db.cursor.executed)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["hosted", "legacy"])
async def test_the_query_and_its_results_are_saved_together(monkeypatch, shape):
    db = fake_db(monkeypatch, shape, fail_on="recommendations")

    with pytest.raises(RuntimeError):
        await save()

    assert db.commits == 0  # the query row is not left behind without its results


@pytest.mark.asyncio
async def test_a_query_with_no_results_is_still_saved(monkeypatch):
    db = fake_db(monkeypatch, "legacy")

    await save(results=[])

    assert len(db.cursor.executed) == 1
    assert db.commits == 1


# AC: recommendations reference game ids rather than copying metadata.

@pytest.mark.asyncio
async def test_hosted_results_store_the_game_id_not_a_copied_title(monkeypatch):
    db = fake_db(monkeypatch, "hosted")

    await save()

    results_sql, results_params = db.cursor.executed[1]
    assert "title" not in results_sql
    assert all("Stardew Valley" not in row for row in results_params)


@pytest.mark.asyncio
async def test_hosted_save_skips_a_result_that_matched_no_game(monkeypatch):
    # The hosted game_id is NOT NULL: a title the LLM made up has nothing to
    # reference, and one bad row must not lose the whole query.
    db = fake_db(monkeypatch, "hosted")
    results = [RESULTS[0], recommendation(2, "Not In The Catalogue"), RESULTS[2]]

    await save(results=results)

    _, results_params = db.cursor.executed[1]
    assert [row[2] for row in results_params] == [1, 3]


@pytest.mark.asyncio
async def test_hosted_save_with_no_catalogue_games_saves_just_the_query(monkeypatch):
    db = fake_db(monkeypatch, "hosted")

    await save(results=[recommendation(1, "Made Up")])

    assert len(db.cursor.executed) == 1
    assert db.commits == 1


@pytest.mark.asyncio
async def test_hosted_history_reads_titles_from_the_catalogue(monkeypatch):
    db = fake_db(monkeypatch, "hosted")

    await repositories.list_query_history(USER, limit=5)

    (sql, _), = db.cursor.executed
    assert "join public.games g on g.game_id = r.game_id" in sql
    assert "g.title" in sql
    assert "r.title" not in sql


@pytest.mark.asyncio
async def test_legacy_history_prefers_the_catalogue_title(monkeypatch):
    db = fake_db(monkeypatch, "legacy")

    await repositories.list_query_history(USER, limit=5)

    (sql, _), = db.cursor.executed
    assert "coalesce(g.title, r.title)" in sql


# AC: history survives sign-out and sign-in (it is keyed by user, not session).

def history_row(query_id, text, asked_at, rank=None, title=None, game_id=None):
    reason = f"why {title}" if title else None
    generated_at = asked_at if rank is not None else None
    return (query_id, text, asked_at, rank, game_id, title, reason, None, generated_at)


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["hosted", "legacy"])
async def test_history_is_read_by_user_newest_first_and_limited(monkeypatch, shape):
    db = fake_db(monkeypatch, shape)

    await repositories.list_query_history(USER, limit=7)

    (sql, params), = db.cursor.executed
    assert "where user_id = %s" in sql
    assert "order by created_at desc" in sql
    assert params == (str(USER), 7)


@pytest.mark.asyncio
async def test_results_are_grouped_under_their_query_in_rank_order(monkeypatch):
    newer, older = uuid4(), uuid4()
    rows = [
        history_row(newer, "cozy farming", ASKED_AT, 1, "Stardew Valley"),
        history_row(newer, "cozy farming", ASKED_AT, 2, "Dinkum"),
        history_row(older, "hard roguelike", ASKED_AT - timedelta(days=1), 1, "Hades"),
    ]
    fake_db(monkeypatch, "legacy", rows=rows)

    entries = await repositories.list_query_history(USER, limit=5)

    assert [e.query_id for e in entries] == [newer, older]
    assert entries[0].query == "cozy farming"
    assert entries[0].created_at == ASKED_AT
    assert [(r.rank, r.title) for r in entries[0].recommendations] == [
        (1, "Stardew Valley"), (2, "Dinkum"),
    ]
    assert [r.title for r in entries[1].recommendations] == ["Hades"]


@pytest.mark.asyncio
async def test_a_query_with_no_saved_results_is_listed_with_none(monkeypatch):
    query_id = uuid4()
    fake_db(monkeypatch, "hosted", rows=[history_row(query_id, "made up game", ASKED_AT)])

    [entry] = await repositories.list_query_history(USER, limit=5)

    assert entry.query_id == query_id
    assert entry.recommendations == []


# TM11-69 AC-02: a saved result reads back with its rank, explanation and
# generated_at.

@pytest.mark.asyncio
@pytest.mark.parametrize("shape, column", [
    ("hosted", "r.generated_at"), ("legacy", "r.created_at"),
])
async def test_history_reads_each_results_own_time(monkeypatch, shape, column):
    db = fake_db(monkeypatch, shape)

    await repositories.list_query_history(USER, limit=5)

    (sql, _), = db.cursor.executed
    assert f"g.steam_appid, {column} " in sql


@pytest.mark.asyncio
async def test_a_history_result_carries_rank_explanation_and_generated_at(monkeypatch):
    query_id = uuid4()
    row = history_row(query_id, "cozy farming", ASKED_AT, 1, "Stardew Valley")
    fake_db(monkeypatch, "hosted", rows=[row])

    [entry] = await repositories.list_query_history(USER, limit=5)

    [result] = entry.recommendations
    assert (result.rank, result.reason, result.generated_at) == (
        1, "why Stardew Valley", ASKED_AT,
    )


# AC: writes do not block the user response.

@pytest.mark.asyncio
async def test_a_failed_save_is_logged_not_raised(monkeypatch, caplog):
    async def fail(**_):
        raise RuntimeError("connection to db.secret-host lost")

    monkeypatch.setattr(repositories, "save_query_history", fail)
    query_id = uuid4()

    with caplog.at_level(logging.ERROR, logger="gamegpt.history"):
        await query_history.record_query(
            query_id=query_id, user_id=USER, query="cozy", recommendations=RESULTS,
        )

    [record] = caplog.records
    assert record.query_id == str(query_id)
    assert record.exc_info is not None


class FakePipeline:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def recommend_outcome(self, user_id, query, *, timings=None):
        return RecommendOutcome(RESULTS)


@pytest.fixture
def saved(monkeypatch) -> list[dict]:
    """POST /api/recommend with a faked pipeline, capturing what it saves."""
    calls: list[dict] = []

    async def capture(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(recommend_router, "RAGPipeline", FakePipeline)
    monkeypatch.setattr(repositories, "save_query_history", capture)
    return calls


def test_recommend_saves_what_it_returned(saved):
    resp = TestClient(create_app()).post("/api/recommend", json={"query": "cozy farming game"})

    assert resp.status_code == 200
    body = resp.json()
    [call] = saved
    assert call["query_id"] == UUID(body["query_id"])
    assert call["user_id"] == UUID(get_settings().dev_user_id)
    assert call["query"] == "cozy farming game"
    assert call["recommendations"] == RESULTS


def test_recommend_answers_even_when_the_save_fails(monkeypatch):
    async def fail(**_):
        raise RuntimeError("connection to db.secret-host lost")

    monkeypatch.setattr(recommend_router, "RAGPipeline", FakePipeline)
    monkeypatch.setattr(repositories, "save_query_history", fail)
    client = TestClient(create_app(), raise_server_exceptions=False)

    resp = client.post("/api/recommend", json={"query": "cozy farming game"})

    assert resp.status_code == 200
    assert [r["title"] for r in resp.json()["recommendations"]] == [r.title for r in RESULTS]


def test_recommend_saves_after_the_response_is_built(monkeypatch):
    # The save is a background task: it is not awaited inside the handler.
    order: list[str] = []
    real_response = recommend_router.RecommendResponse

    def response(**kwargs):
        order.append("response")
        return real_response(**kwargs)

    async def capture(**_):
        order.append("save")

    monkeypatch.setattr(recommend_router, "RAGPipeline", FakePipeline)
    monkeypatch.setattr(recommend_router, "RecommendResponse", response)
    monkeypatch.setattr(repositories, "save_query_history", capture)

    TestClient(create_app()).post("/api/recommend", json={"query": "cozy farming game"})

    assert order == ["response", "save"]


def test_each_recommend_call_gets_its_own_query_id(saved):
    client = TestClient(create_app())

    first = client.post("/api/recommend", json={"query": "cozy"}).json()["query_id"]
    second = client.post("/api/recommend", json={"query": "cozy"}).json()["query_id"]

    assert first != second


# GET /api/history.

ENTRY = {
    "query_id": uuid4(), "query": "cozy farming", "created_at": ASKED_AT,
    "recommendations": [{"rank": 1, "game_id": RESULTS[0].game_id, "title": "Stardew Valley",
                         "reason": "why Stardew Valley", "steam_appid": 413150}],
}


@pytest.fixture
def listed(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []

    async def fake_list(user_id, *, limit):
        calls.append((user_id, limit))
        return [HistoryEntry(**ENTRY)]

    monkeypatch.setattr(repositories, "list_query_history", fake_list)
    return calls


def test_history_returns_the_dev_users_queries(listed):
    resp = TestClient(create_app()).get("/api/history")

    assert resp.status_code == 200
    [item] = resp.json()["items"]
    assert item["query"] == "cozy farming"
    assert item["recommendations"][0]["title"] == "Stardew Valley"
    assert listed == [(UUID(get_settings().dev_user_id), 20)]


@pytest.mark.parametrize("limit", [1, 50])
def test_history_limit_is_passed_through(listed, limit):
    TestClient(create_app()).get("/api/history", params={"limit": limit})
    assert listed[-1][1] == limit


@pytest.mark.parametrize("limit", [0, 51, -1])
def test_history_limit_out_of_range_is_rejected(listed, limit):
    resp = TestClient(create_app()).get("/api/history", params={"limit": limit})

    assert resp.status_code == 422
    assert listed == []


def test_history_db_failure_is_a_503_without_the_cause(monkeypatch):
    async def fail(user_id, *, limit):
        raise RuntimeError("connection to db.secret-host lost")

    monkeypatch.setattr(repositories, "list_query_history", fail)
    client = TestClient(create_app(), raise_server_exceptions=False)

    resp = client.get("/api/history")

    assert resp.status_code == 503
    assert resp.json()["detail"] == {
        "error": "db_unavailable",
        "message": history_router.HISTORY_FAILED_MESSAGE,
    }
    assert "secret-host" not in resp.text
