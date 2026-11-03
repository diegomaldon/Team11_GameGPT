"""DELETE /api/library/platforms/{platform} (TM11-61, REQ003).

Disconnecting a platform has to take its games out of the library the web app
reads, and only its games: a title also owned on a platform that is still
linked stays. The route tests fake the DB layer with an in-memory owned_games;
the last group runs the real SQL on the legacy shape and skips without a
database, like test_db_backed.py.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import connection, has_db, repositories
from api.db.schema import catalogue_shape
from api.main import create_app
from api.services.library_sync import sync_jobs

DEV_USER = UUID(get_settings().dev_user_id)


class FakeLibrary:
    def __init__(self) -> None:
        # (user, platform, title)
        self.rows: list[tuple[UUID, str, str]] = [
            (DEV_USER, "steam", "Hades"),
            (DEV_USER, "xbox", "Hades"),
            (DEV_USER, "steam", "Rust"),
            (DEV_USER, "epic", "Celeste"),
        ]
        self.fail = False

    def titles(self, platform: str) -> list[str]:
        return [t for _, p, t in self.rows if p == platform]


@pytest.fixture
def library(monkeypatch) -> FakeLibrary:
    lib = FakeLibrary()

    async def remove_platform_games(user_id, platform):
        if lib.fail:
            raise psycopg.OperationalError("connection refused")
        before = len(lib.rows)
        lib.rows = [r for r in lib.rows if not (r[0] == user_id and r[1] == platform)]
        return before - len(lib.rows)

    monkeypatch.setattr(repositories, "remove_platform_games", remove_platform_games)
    return lib


@pytest.fixture
def client(library) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _remove(client: TestClient, platform: str):
    return client.delete(f"/api/library/platforms/{platform}")


# ── AC2: the platform's owned_games are removed ──────────────────────────────


def test_removes_every_game_on_the_platform(client, library):
    res = _remove(client, "steam")
    assert res.status_code == 200
    assert res.json() == {"platform": "steam", "removed": 2}
    assert library.titles("steam") == []


def test_a_second_call_removes_nothing_and_still_succeeds(client, library):
    _remove(client, "steam")
    res = _remove(client, "steam")
    assert res.status_code == 200
    assert res.json()["removed"] == 0


@pytest.mark.parametrize("platform", ["playstation", "STEAM", "all"])
def test_refuses_a_platform_that_cant_be_linked(client, library, platform):
    assert _remove(client, platform).status_code == 422
    assert len(library.rows) == 4


def test_a_failed_delete_is_a_structured_503(client, library):
    library.fail = True
    res = _remove(client, "steam")
    assert res.status_code == 503
    assert res.json()["detail"]["error"] == "remove_failed"
    assert "connection refused" not in res.text


# ── AC3: a title also owned on a still-linked platform stays ─────────────────


def test_other_platforms_keep_their_copies(client, library):
    _remove(client, "steam")
    assert library.titles("xbox") == ["Hades"]
    assert library.titles("epic") == ["Celeste"]


# ── a running Steam import would write the games straight back ───────────────


def test_refuses_steam_while_a_steam_import_is_running(client, library, monkeypatch):
    monkeypatch.setattr(sync_jobs, "running", lambda user_id: user_id == DEV_USER)
    res = _remove(client, "steam")
    assert res.status_code == 409
    assert res.json()["detail"]["error"] == "sync_running"
    assert library.titles("steam") == ["Hades", "Rust"]


def test_a_running_steam_import_does_not_block_other_platforms(client, library, monkeypatch):
    monkeypatch.setattr(sync_jobs, "running", lambda user_id: True)
    assert _remove(client, "xbox").status_code == 200
    assert library.titles("xbox") == []


# ── the SQL each shape sends ──────────────────────────────────────────────────
# db-seeded only builds the legacy shape, so the hosted delete never meets a real
# database in CI. These pin the statement and its parameters for both shapes.


class _FakeCursor:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, params):
        self.executed.append((sql, params))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    async def commit(self):
        self.committed = True


@pytest.fixture
def fake_db(monkeypatch):
    def install(shape: str, rowcount: int = 2) -> tuple[_FakeCursor, _FakeConnection]:
        cursor = _FakeCursor(rowcount)
        conn = _FakeConnection(cursor)

        @asynccontextmanager
        async def connection():
            yield conn

        async def catalogue_shape():
            return shape

        monkeypatch.setattr(repositories, "connection", connection)
        monkeypatch.setattr(repositories, "catalogue_shape", catalogue_shape)
        return cursor, conn

    return install


@pytest.mark.asyncio
async def test_hosted_delete_goes_through_the_users_platform_account(fake_db):
    cursor, conn = fake_db("hosted")
    user = uuid4()
    assert await repositories.remove_platform_games(user, "steam") == 2
    ((sql, params),) = cursor.executed
    normalised = " ".join(sql.split())
    assert "delete from owned_games og using platform_accounts pa" in normalised
    assert "og.platform_account_id = pa.platform_account_id" in normalised
    # platform_type is STEAM/XBOX/EPIC; the path value is lower case.
    assert "pa.user_id = %s and pa.platform::text = upper(%s)" in normalised
    assert params == (str(user), "steam")
    assert conn.committed


@pytest.mark.asyncio
async def test_legacy_delete_filters_by_user_and_platform(fake_db):
    cursor, conn = fake_db("legacy")
    user = uuid4()
    assert await repositories.remove_platform_games(user, "xbox") == 2
    ((sql, params),) = cursor.executed
    assert sql == "delete from owned_games where user_id = %s and platform = %s"
    assert params == (str(user), "xbox")
    assert conn.committed


@pytest.mark.asyncio
async def test_an_unknown_rowcount_reports_zero(fake_db):
    # psycopg reports -1 when the count isn't available; never send that to the UI.
    fake_db("legacy", rowcount=-1)
    assert await repositories.remove_platform_games(uuid4(), "epic") == 0


# ── the real SQL, legacy shape ────────────────────────────────────────────────


async def _legacy_db() -> None:
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    try:
        if await catalogue_shape() != "legacy":
            pytest.skip("hosted shape: owned_games rows go by cascade from platform_accounts")
    except psycopg.Error as exc:
        pytest.skip(f"DB not usable: {exc}")


@pytest.mark.asyncio
async def test_sql_removes_one_platform_for_one_user():
    await _legacy_db()
    user, other = uuid4(), uuid4()
    async with connection() as conn:
        async with conn.cursor() as cur:
            for u in (user, other):
                await cur.execute(
                    "insert into users (id, email) values (%s, %s)",
                    (str(u), f"tm11-61-{u}@test.local"),
                )
            await cur.executemany(
                "insert into owned_games (user_id, platform, steam_appid, title) "
                "values (%s, %s, %s, %s)",
                [
                    (str(user), "steam", 1145360, "Hades"),
                    (str(user), "xbox", None, "Hades"),
                    (str(user), "steam", 252490, "Rust"),
                    (str(other), "steam", 1145360, "Hades"),
                ],
            )
        await conn.commit()
    try:
        assert await repositories.remove_platform_games(user, "steam") == 2
        assert [(i.title, i.platform) for i in await repositories.list_owned_games(user)] == [
            ("Hades", "xbox")
        ]
        # Someone else's Steam library is untouched.
        assert len(await repositories.list_owned_games(other)) == 1
        assert await repositories.remove_platform_games(user, "steam") == 0
    finally:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "delete from users where id = any(%s::uuid[])", ([str(user), str(other)],)
                )
            await conn.commit()
