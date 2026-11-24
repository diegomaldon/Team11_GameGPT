"""Response caching for repeated queries (TM11-73, REQ040).

One group per acceptance criterion. The cache itself is pure; the API tests
fake the pipeline and the library fingerprint, so no database or model is
needed. The fingerprint SQL is checked against a fake cursor here and was run
against Postgres by hand (see the PR).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.main import create_app
from api.models import Recommendation, RecommendNotice
from api.routers import recommend as recommend_router
from api.services import deduplication
from api.services.deduplication import DeduplicationService
from api.services.rag_pipeline import ALL_OWNED_NOTICE, RecommendOutcome
from api.services.response_cache import (
    CACHE_TTL_SECONDS,
    ResponseCache,
    cache_key,
    normalise_query,
)

USER = uuid4()
# TM11-72's notice (#67); built here so this PR doesn't depend on that one.
RANKING_DEGRADED_NOTICE = RecommendNotice(code="ranking_degraded", message="Unranked.")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ───── AC: identical query and library state served from cache ─────


def test_the_same_key_is_served_from_the_cache():
    cache: ResponseCache[str] = ResponseCache()
    key = cache_key(USER, "cozy farming", "3:abc")
    cache.put(key, "answer")
    assert cache.get(key) == "answer"


@pytest.mark.parametrize("a, b", [
    ("Cozy farming", "cozy farming"),
    ("cozy   farming ", " cozy farming"),
])
def test_whitespace_and_case_dont_make_a_new_query(a, b):
    assert normalise_query(a) == normalise_query(b)
    assert cache_key(USER, a, "fp") == cache_key(USER, b, "fp")


def test_another_query_or_another_user_misses():
    cache: ResponseCache[str] = ResponseCache()
    cache.put(cache_key(USER, "cozy farming", "fp"), "answer")
    assert cache.get(cache_key(USER, "scary horror", "fp")) is None
    assert cache.get(cache_key(uuid4(), "cozy farming", "fp")) is None


def test_entries_expire_after_the_ttl():
    clock = FakeClock()
    cache: ResponseCache[str] = ResponseCache(clock=clock)
    cache.put("k", "answer")
    clock.now += CACHE_TTL_SECONDS - 1
    assert cache.get("k") == "answer"
    clock.now += 2
    assert cache.get("k") is None
    assert cache.stats().entries == 0


def test_the_least_recently_used_entry_is_dropped_past_the_limit():
    cache: ResponseCache[str] = ResponseCache(max_entries=2)
    cache.put("a", "1")
    cache.put("b", "2")
    cache.get("a")  # a is now the most recent
    cache.put("c", "3")
    assert (cache.get("a"), cache.get("b"), cache.get("c")) == ("1", None, "3")


def test_bad_settings_are_rejected():
    with pytest.raises(ValueError):
        ResponseCache(ttl_seconds=0)
    with pytest.raises(ValueError):
        ResponseCache(max_entries=0)


# ───── AC: cache invalidated on library change ─────


def test_a_changed_library_fingerprint_misses():
    cache: ResponseCache[str] = ResponseCache()
    cache.put(cache_key(USER, "cozy farming", "3:abc"), "computed with 3 games")
    assert cache.get(cache_key(USER, "cozy farming", "4:def")) is None


class _FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executed: list[tuple[str, tuple]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params):
        self.executed.append((sql, params))

    async def fetchone(self):
        return self.row


def _fake_db(monkeypatch, shape: str, row):
    cursor = _FakeCursor(row)

    class Conn:
        def cursor(self):
            return cursor

    @asynccontextmanager
    async def connection():
        yield Conn()

    async def catalogue_shape():
        return shape

    monkeypatch.setattr(deduplication, "connection", connection)
    monkeypatch.setattr(deduplication, "catalogue_shape", catalogue_shape)
    monkeypatch.setattr(deduplication, "has_db", lambda: True)
    return cursor


@pytest.mark.asyncio
@pytest.mark.parametrize("shape, table", [("hosted", "public.owned_games o"),
                                          ("legacy", "from owned_games")])
async def test_the_fingerprint_hashes_every_owned_row_for_the_user(monkeypatch, shape, table):
    cursor = _fake_db(monkeypatch, shape, (3, "abc123"))

    fp = await DeduplicationService().library_fingerprint(USER)

    assert fp == "3:abc123"
    [(sql, params)] = cursor.executed
    assert table in sql and "md5(" in sql and "string_agg(" in sql and "order by" in sql
    assert params == (USER,)


@pytest.mark.asyncio
async def test_no_database_means_no_fingerprint(monkeypatch):
    monkeypatch.setattr(deduplication, "has_db", lambda: False)
    assert await DeduplicationService().library_fingerprint(USER) is None


# ───── API: hits skip the pipeline, misses run it, and the hit rate is logged ─────


class CountingPipeline:
    """Stands in for RAGPipeline; counts runs and returns `outcome`."""

    runs = 0
    outcome = RecommendOutcome(recommendations=[
        Recommendation(rank=1, title="Stardew Valley", reason="Cozy farming."),
    ])

    def __init__(self, *args, **kwargs):
        pass

    async def recommend_outcome(self, user_id, query, *, timings=None):
        type(self).runs += 1
        return type(self).outcome


@pytest.fixture
def library(monkeypatch):
    """The library fingerprint the API sees; change `state["fp"]` to change the library."""
    state = {"fp": "3:abc"}

    async def fingerprint(self, user_id):
        if isinstance(state["fp"], Exception):
            raise state["fp"]
        return state["fp"]

    monkeypatch.setattr(DeduplicationService, "library_fingerprint", fingerprint)
    return state


@pytest.fixture
def client(monkeypatch, library) -> TestClient:
    async def no_save(**_):
        return None

    monkeypatch.setattr(repositories, "save_query_history", no_save)
    CountingPipeline.runs = 0
    CountingPipeline.outcome = RecommendOutcome(recommendations=[
        Recommendation(rank=1, title="Stardew Valley", reason="Cozy farming."),
    ])
    monkeypatch.setattr(recommend_router, "RAGPipeline", CountingPipeline)
    return TestClient(create_app())


def _ask(client, query="cozy farming game"):
    resp = client.post("/api/recommend", json={"query": query})
    assert resp.status_code == 200
    return resp.json()


def test_a_repeated_query_is_served_without_running_the_pipeline(client):
    first = _ask(client)
    second = _ask(client, "  Cozy farming GAME ")

    assert CountingPipeline.runs == 1
    assert second["recommendations"] == first["recommendations"]
    # A hit is still its own query, saved under a new id.
    assert second["query_id"] != first["query_id"]


def test_a_library_change_runs_the_pipeline_again(client, library):
    _ask(client)
    library["fp"] = "4:def"  # e.g. a game was imported
    _ask(client)
    _ask(client)

    assert CountingPipeline.runs == 2


def test_a_degraded_ranking_is_not_cached(client):
    CountingPipeline.outcome = RecommendOutcome(
        recommendations=[Recommendation(rank=1, title="Unpacking", reason="Calm.")],
        notice=RANKING_DEGRADED_NOTICE,
    )
    _ask(client)
    _ask(client)

    assert CountingPipeline.runs == 2


def test_an_all_owned_answer_is_cached_for_that_library(client):
    CountingPipeline.outcome = RecommendOutcome(recommendations=[], notice=ALL_OWNED_NOTICE)
    first = _ask(client)
    second = _ask(client)

    assert CountingPipeline.runs == 1
    assert second["notice"] == first["notice"]


def test_an_unreadable_library_skips_the_cache_instead_of_failing(client, library, caplog):
    library["fp"] = RuntimeError("database down")
    _ask(client)
    _ask(client)

    assert CountingPipeline.runs == 2
    assert any(r.msg == "recommend.cache_unavailable" for r in caplog.records)


# ───── AC: hit rate logged ─────


def test_every_lookup_logs_the_running_hit_rate(client, caplog):
    caplog.set_level(logging.INFO, logger="gamegpt.cache")
    for query in ("cozy farming game", "cozy farming game", "scary horror", "cozy farming game"):
        _ask(client, query)

    lines = [r for r in caplog.records if r.msg == "recommend.cache"]
    assert [r.cache_hit for r in lines] == [False, True, False, True]
    assert [r.cache_stored for r in lines] == [True, None, True, None]
    assert lines[-1].cache_lookups == 4
    assert lines[-1].cache_hits == 2
    assert lines[-1].cache_hit_rate == 0.5
    assert lines[-1].cache_entries == 2
    assert all(r.lookup_ms is not None for r in lines)
    # The query text never reaches the log line.
    assert not any("cozy" in str(r.__dict__.values()) for r in lines)


def test_changing_a_served_answer_doesnt_change_the_cached_one(client):
    # PR #68 review: a hit used to hand back the stored objects themselves.
    _ask(client)
    [(_, stored)] = list(recommend_router.RESPONSE_CACHE._entries.values())
    served = recommend_router._copy_of(stored)
    served.recommendations[0].title = "MUTATED"
    served.recommendations.append(served.recommendations[0])

    assert _ask(client)["recommendations"][0]["title"] == "Stardew Valley"
    assert len(stored.recommendations) == 1


def test_a_served_copy_doesnt_share_nested_lists_with_the_cache():
    # A shallow model_copy() would share a Recommendation's own lists, such as
    # TM11-75's `platforms` (#71), between the cached entry and every hit.
    class WithPlatforms(Recommendation):
        platforms: list[str] = []

    stored = RecommendOutcome(recommendations=[
        WithPlatforms(rank=1, title="Hades", reason="Fast.", platforms=["steam"]),
    ])
    served = recommend_router._copy_of(stored)
    served.recommendations[0].platforms.append("xbox")

    assert stored.recommendations[0].platforms == ["steam"]
