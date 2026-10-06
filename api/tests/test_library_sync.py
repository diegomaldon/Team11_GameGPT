"""TM11-49: library import progress and partial-failure handling.

No Postgres needed. `FakeConn` models psycopg's transaction() semantics: the
outermost block commits on clean exit, nested blocks are savepoints, and any
exception rolls back to where the block began. That is exactly the contract
import_owned_games relies on, so these tests exercise the real code path.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest

from api.config import Settings
from api.db import repositories
from api.main import app
from api.models import SyncJobState
from api.services import library_sync
from api.services.library_sync import (
    SYNC_FAILED_MESSAGE,
    LibrarySyncService,
    SyncJobRegistry,
    new_job,
)
from api.services.steam_client import OwnedGame, SteamClient, SteamPrivateProfileError

pytestmark = pytest.mark.asyncio

USER = UUID("00000000-0000-0000-0000-000000000001")
STEAM_ID = "76561197960287930"  # SteamClient rejects anything that is not a steamID64


# ───────────────────────────── fake Postgres ─────────────────────────────


class FakeDB:
    def __init__(self, committed: dict[tuple, str | None] | None = None) -> None:
        self.committed: dict[tuple, str | None] = dict(committed or {})
        self.bad_appids: set[int] = set()       # raise DataError (a bad title)
        self.crash_on_appid: int | None = None  # raise OperationalError (run dies)
        self.playtime: dict[int, int] = {}      # last playtime_minutes written per appid

    def factory(self):
        db = self

        @asynccontextmanager
        async def _connect():
            yield FakeConn(db)

        return _connect


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self._conn = conn

    async def __aenter__(self) -> "FakeCursor":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, sql: str, params: tuple) -> None:
        user, platform, appid, title, playtime, _game_id = params
        if appid == self._conn.db.crash_on_appid:
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        if appid in self._conn.db.bad_appids:
            raise psycopg.DataError("integer out of range")
        self._conn.work[(user, platform, appid)] = title
        self._conn.db.playtime[appid] = playtime

    async def executemany(self, sql: str, seq: list[tuple]) -> None:
        for params in seq:
            await self.execute(sql, params)


class FakeConn:
    def __init__(self, db: FakeDB) -> None:
        self.db = db
        self.depth = 0
        self.work: dict[tuple, str | None] = {}

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    @asynccontextmanager
    async def transaction(self):
        if self.depth == 0:
            self.work = dict(self.db.committed)
        snapshot = dict(self.work)
        self.depth += 1
        try:
            yield
        except BaseException:
            self.work = snapshot  # ROLLBACK [TO SAVEPOINT]
            raise
        finally:
            self.depth -= 1
        if self.depth == 0:
            self.db.committed = self.work  # COMMIT


def games(n: int, start: int = 1) -> list[dict[str, Any]]:
    return [{"steam_appid": i, "title": f"Game {i}"} for i in range(start, start + n)]


def owned(db: FakeDB) -> set[int]:
    return {k[2] for k in db.committed}


# ─────────────────────── repositories.import_owned_games ───────────────────────


async def test_import_reports_progress_per_chunk() -> None:
    db = FakeDB()
    seen: list[tuple[int, int]] = []
    synced, failures = await repositories.import_owned_games(
        USER, games(120), chunk_size=50, conn_factory=db.factory(),
        on_progress=lambda done, ok, f: seen.append((done, ok)),
    )
    assert (synced, failures) == (120, [])
    assert seen == [(50, 50), (100, 100), (120, 120)]
    assert owned(db) == set(range(1, 121))


async def test_bad_titles_are_reported_and_the_run_continues() -> None:
    db = FakeDB()
    db.bad_appids = {7, 88}
    synced, failures = await repositories.import_owned_games(
        USER, games(120), chunk_size=50, conn_factory=db.factory()
    )
    assert synced == 118
    assert [row["steam_appid"] for row, _ in failures] == [7, 88]
    assert all(reason.startswith("DataError") for _, reason in failures)
    # every other title in the failing chunks still landed
    assert owned(db) == set(range(1, 121)) - {7, 88}


async def test_failed_run_leaves_previous_library_intact() -> None:
    before = {(str(USER), "steam", 1): "Old A", (str(USER), "steam", 2): "Old B"}
    db = FakeDB(before)
    db.crash_on_appid = 75  # dies in the second chunk, after chunk 1 "succeeded"
    with pytest.raises(psycopg.OperationalError):
        await repositories.import_owned_games(
            USER, games(120), chunk_size=50, conn_factory=db.factory()
        )
    assert db.committed == before


# ───────────────────────────── service + jobs ─────────────────────────────


def steam_client(payload: dict | None = None, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload or {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def steam_payload(appids: list[Any]) -> dict:
    # game_count matters: without it Steam is saying the profile is private.
    games = [{"appid": a, "name": f"Game {a}", "playtime_forever": 60} for a in appids]
    return {"response": {"game_count": len(games), "games": games}}


async def _no_sleep(_seconds: float) -> None:
    return None


def service(http_client: httpx.AsyncClient) -> LibrarySyncService:
    """A keyed service whose Steam retries and pacing do not really sleep."""
    settings = keyed()
    steam = SteamClient(settings=settings, http_client=http_client, sleep=_no_sleep)
    return LibrarySyncService(settings=settings, steam_client=steam)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeDB:
    db = FakeDB()
    real = repositories.import_owned_games

    async def patched(*args: Any, **kwargs: Any):
        kwargs.setdefault("conn_factory", db.factory())
        return await real(*args, **kwargs)

    monkeypatch.setattr(repositories, "import_owned_games", patched)

    # Title matching reads the catalogue and records the run; no Postgres here.
    async def no_catalogue() -> list:
        return []

    async def record_import(*args: Any, **kwargs: Any) -> UUID:
        return uuid4()

    monkeypatch.setattr(repositories, "list_catalogue_games", no_catalogue)
    monkeypatch.setattr(repositories, "record_library_import", record_import)
    return db


def keyed() -> Settings:
    return Settings(steam_api_key="test-key")


async def test_service_tracks_job_and_reports_failures(fake_db: FakeDB) -> None:
    fake_db.bad_appids = {30}
    appids: list[Any] = list(range(1, 61)) + [-5, 0, 10]  # 2 invalid ids + 1 repeat
    svc = service(steam_client(steam_payload(appids)))
    job = new_job()
    res = await svc.sync(USER, STEAM_ID, job)

    assert job.state is SyncJobState.succeeded and job.finished_at is not None
    assert (res.total, res.synced, len(res.failed)) == (62, 59, 3)
    assert job.processed == job.total == 62
    reasons = {f.reason.split(":")[0] for f in res.failed}
    assert reasons == {"invalid appid -5", "invalid appid 0", "DataError"}
    assert 30 not in owned(fake_db) and len(owned(fake_db)) == 59


async def test_import_writes_playtime(fake_db: FakeDB) -> None:
    """TM11-46: playtime from Steam has to reach owned_games on the job path too."""
    payload = {"response": {"game_count": 2, "games": [
        {"appid": 252490, "name": "Rust", "playtime_forever": 129351},
        {"appid": 431960, "name": "Wallpaper Engine", "playtime_forever": 0},
    ]}}
    await service(steam_client(payload)).sync(USER, STEAM_ID)
    assert fake_db.playtime == {252490: 129351, 431960: 0}


async def test_steam_error_fails_without_touching_library(fake_db: FakeDB) -> None:
    fake_db.committed = {(str(USER), "steam", 1): "Kept"}
    svc = service(steam_client(status_code=500))
    with pytest.raises(Exception):
        await svc.sync(USER, STEAM_ID)
    assert fake_db.committed == {(str(USER), "steam", 1): "Kept"}


async def test_registry_runs_job_in_background(fake_db: FakeDB) -> None:
    gate = asyncio.Event()

    class SlowSteam:
        async def get_owned_games(self, steam_id: str) -> list[OwnedGame]:
            await gate.wait()
            return [OwnedGame(appid=i, playtime_minutes=0, name=f"Game {i}")
                    for i in range(1, 11)]

    reg = SyncJobRegistry(service_factory=lambda: LibrarySyncService(
        settings=keyed(), steam_client=SlowSteam()))
    job = reg.start(USER, STEAM_ID)
    await asyncio.sleep(0)
    assert reg.get(job.job_id, USER).state is SyncJobState.fetching
    assert reg.start(USER, STEAM_ID).job_id == job.job_id  # no second concurrent run
    assert reg.get(job.job_id, uuid4()) is None        # other users can't see it

    gate.set()
    await reg.wait(job.job_id)
    done = reg.get(job.job_id, USER)
    assert (done.state, done.synced, done.processed, done.total) == (
        SyncJobState.succeeded, 10, 10, 10)


async def test_registry_marks_failed_job_with_safe_message(fake_db: FakeDB) -> None:
    fake_db.committed = {(str(USER), "steam", 1): "Kept"}
    fake_db.crash_on_appid = 3
    reg = SyncJobRegistry(service_factory=lambda: service(
        steam_client(steam_payload([1, 2, 3, 4]))))
    job = reg.start(USER, STEAM_ID)
    await reg.wait(job.job_id)
    assert job.state is SyncJobState.failed
    assert job.error == SYNC_FAILED_MESSAGE
    assert job.error_code == "sync_failed"
    assert fake_db.committed == {(str(USER), "steam", 1): "Kept"}
    assert reg.start(USER, STEAM_ID).job_id != job.job_id  # a retry gets a fresh job


async def test_private_profile_job_carries_the_explainable_error(
    fake_db: FakeDB, caplog: pytest.LogCaptureFixture
) -> None:
    """TM11-46 AC-02 on the path Settings uses: the job, not POST /library/sync."""
    fake_db.committed = {(str(USER), "steam", 1): "Kept"}
    reg = SyncJobRegistry(service_factory=lambda: service(
        steam_client({"response": {}})))  # what Steam sends for a private profile
    with caplog.at_level("INFO"):
        job = reg.start(USER, STEAM_ID)
        await reg.wait(job.job_id)

    assert job.state is SyncJobState.failed
    assert job.error_code == "steam_profile_private"
    assert job.error == SteamPrivateProfileError(STEAM_ID).user_message
    assert fake_db.committed == {(str(USER), "steam", 1): "Kept"}
    # A private profile is a user setting, not a crash: no stack trace, and the
    # steamID does not reach the job-runner's log line.
    runner = [r for r in caplog.records if "library sync job" in r.getMessage()]
    assert runner and all(r.exc_info is None for r in runner)
    assert all(STEAM_ID not in r.getMessage() for r in runner)


async def test_registry_prunes_old_finished_jobs(fake_db: FakeDB) -> None:
    reg = SyncJobRegistry(service_factory=lambda: service(
        steam_client(steam_payload([1]))), max_jobs=3)
    ids = []
    for _ in range(5):
        j = reg.start(USER, STEAM_ID)
        await reg.wait(j.job_id)
        ids.append(j.job_id)
    assert reg.get(ids[0], USER) is None
    assert reg.get(ids[-1], USER) is not None


# ─────────────────────────────── HTTP routes ───────────────────────────────


async def test_job_routes(monkeypatch: pytest.MonkeyPatch, fake_db: FakeDB) -> None:
    reg = SyncJobRegistry(service_factory=lambda: service(
        steam_client(steam_payload([1, 2]))))
    monkeypatch.setattr("api.routers.library.sync_jobs", reg)
    monkeypatch.setattr(library_sync, "sync_jobs", reg)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/library/sync/jobs", json={"steam_id": STEAM_ID})
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        await reg.wait(UUID(job_id))

        r = await client.get(f"/api/library/sync/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()
        assert (body["state"], body["synced"], body["total"]) == ("succeeded", 2, 2)

        r = await client.get(f"/api/library/sync/jobs/{uuid4()}")
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "job_not_found"
