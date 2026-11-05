"""Per-stage recommend timings: the timer, its log fields and the Server-Timing header.

TM11-68 (REQ040). Offline: the clock and the pipeline are faked.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.main import create_app
from api.models import Recommendation
from api.observability.stage_timings import (
    SERVER_TIMING_HEADER,
    STAGE_BUDGET_MS,
    STAGES,
    TOTAL_BUDGET_MS,
    StageTimings,
)
from api.routers import recommend as recommend_router


class FakeClock:
    """perf_counter stand-in that only moves when a test says so."""

    def __init__(self) -> None:
        self.now_seconds = 100.0

    def __call__(self) -> float:
        return self.now_seconds

    def advance(self, ms: float) -> None:
        self.now_seconds += ms / 1000


def test_each_stage_is_timed_in_milliseconds():
    clock = FakeClock()
    timings = StageTimings(clock=clock)

    with timings.stage("parse"):
        clock.advance(2.5)
    with timings.stage("embed"):
        clock.advance(40)

    fields = timings.log_fields()
    assert fields["parse_ms"] == 2.5
    assert fields["embed_ms"] == 40.0


def test_the_total_is_the_sum_of_the_stages():
    clock = FakeClock()
    timings = StageTimings(clock=clock)

    for stage, ms in zip(STAGES, [1, 2, 3, 4, 5]):
        with timings.stage(stage):
            clock.advance(ms)

    assert timings.log_fields()["total_ms"] == 15.0


def test_the_log_line_has_every_stage_even_ones_that_never_ran():
    # Same keys on every line, so a jq filter or the report never trips on a missing one.
    timings = StageTimings(clock=FakeClock())

    with timings.stage("parse"):
        pass

    fields = timings.log_fields()
    assert set(fields) == {f"{s}_ms" for s in STAGES} | {"total_ms", "failed_stage"}
    assert fields["rank_ms"] is None
    assert fields["failed_stage"] is None


def test_a_failed_stage_is_timed_named_and_still_raised():
    clock = FakeClock()
    timings = StageTimings(clock=clock)

    with pytest.raises(TimeoutError):
        with timings.stage("rank"):
            clock.advance(30_000)
            raise TimeoutError("LLM took too long")

    fields = timings.log_fields()
    assert fields["rank_ms"] == 30_000.0
    assert fields["failed_stage"] == "rank"


def test_a_cancelled_request_counts_as_failed_at_its_stage():
    # A client hanging up cancels the task; that request must not read as finished.
    timings = StageTimings(clock=FakeClock())

    with pytest.raises(asyncio.CancelledError):
        with timings.stage("rank"):
            raise asyncio.CancelledError

    assert timings.log_fields()["failed_stage"] == "rank"


def test_an_unknown_stage_is_rejected():
    # A typo would quietly start a new log field the weekly report never reads.
    timings = StageTimings(clock=FakeClock())

    with pytest.raises(ValueError, match="retreive"):
        with timings.stage("retreive"):
            pass


def test_server_timing_lists_the_stages_that_ran_in_order():
    clock = FakeClock()
    timings = StageTimings(clock=clock)
    with timings.stage("parse"):
        clock.advance(1.3)
    with timings.stage("embed"):
        clock.advance(12)

    assert timings.server_timing() == "parse;dur=1.3, embed;dur=12.0, total;dur=13.3"


def test_the_stage_budgets_fit_inside_req040s_ten_seconds():
    assert TOTAL_BUDGET_MS == 10_000
    assert set(STAGE_BUDGET_MS) == set(STAGES)
    assert sum(STAGE_BUDGET_MS.values()) <= TOTAL_BUDGET_MS


RESULT = Recommendation(rank=1, title="Stardew Valley", reason="Cozy farming.")


class TimedFakePipeline:
    """Fills in every stage the way the real pipeline does, in no time at all."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def recommend(self, user_id, query, *, timings):
        for stage in STAGES:
            with timings.stage(stage):
                pass
        return [RESULT]


class FailingFakePipeline(TimedFakePipeline):
    async def recommend(self, user_id, query, *, timings):
        with timings.stage("rank"):
            raise RuntimeError("LLM provider down")


@pytest.fixture
def client(monkeypatch) -> TestClient:
    async def no_save(**_):
        return None

    monkeypatch.setattr(repositories, "save_query_history", no_save)
    return TestClient(create_app())


def test_recommend_sends_its_stage_timings_as_server_timing(monkeypatch, client):
    monkeypatch.setattr(recommend_router, "RAGPipeline", TimedFakePipeline)

    resp = client.post("/api/recommend", json={"query": "cozy farming game"})

    assert resp.status_code == 200
    names = [part.split(";")[0] for part in resp.headers[SERVER_TIMING_HEADER].split(", ")]
    assert names == [*STAGES, "total"]


def test_a_failed_recommend_sends_no_server_timing(monkeypatch, client):
    # The timings of a failure are in the log line; the 502 stays a plain error.
    monkeypatch.setattr(recommend_router, "RAGPipeline", FailingFakePipeline)

    resp = client.post("/api/recommend", json={"query": "cozy farming game"})

    assert resp.status_code == 502
    assert SERVER_TIMING_HEADER not in resp.headers
