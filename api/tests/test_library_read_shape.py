"""GET /api/library reads owned_games on both database shapes.

The hosted owned_games holds only ids (game_id, platform_account_id), so the
title and appid have to come from games and the platform from the linked
account. Selecting the legacy columns there failed with `column "title" does
not exist` and the library page got a 503. db-seeded only builds the legacy
shape, so these pin the SQL each shape sends and how a row maps back.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from api.db import repositories


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, params):
        self.executed.append((sql, params))

    async def fetchall(self):
        return self._rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor


@pytest.fixture
def fake_db(monkeypatch):
    def install(shape: str, rows: list[tuple]) -> _FakeCursor:
        cursor = _FakeCursor(rows)

        @asynccontextmanager
        async def connection():
            yield _FakeConnection(cursor)

        async def catalogue_shape():
            return shape

        monkeypatch.setattr(repositories, "connection", connection)
        monkeypatch.setattr(repositories, "catalogue_shape", catalogue_shape)
        return cursor

    return install


@pytest.mark.asyncio
async def test_hosted_read_joins_games_and_platform_accounts(fake_db):
    game = uuid4()
    cursor = fake_db("hosted", [(str(game), "Hades", 1145360, "steam", 120)])
    user = uuid4()

    items = await repositories.list_owned_games(user)

    ((sql, params),) = cursor.executed
    normalised = " ".join(sql.split())
    assert "join games g on g.game_id = og.game_id" in normalised
    assert "join platform_accounts pa on pa.platform_account_id = og.platform_account_id" in normalised
    # platform_type is STEAM/XBOX/EPIC; LibraryItem.platform is lower case.
    assert "lower(pa.platform::text)" in normalised
    assert "where og.user_id = %s" in normalised
    # No bare legacy column: hosted owned_games has no title or platform.
    assert " title," not in normalised.replace("g.title", "")
    assert params == (str(user),)
    assert [(i.game_id, i.title, i.steam_appid, i.platform, i.playtime_minutes) for i in items] == [
        (game, "Hades", 1145360, "steam", 120)
    ]


@pytest.mark.asyncio
async def test_legacy_read_keeps_the_local_columns(fake_db):
    cursor = fake_db("legacy", [(None, "Rust", 252490, "xbox", 0)])
    user = uuid4()

    items = await repositories.list_owned_games(user)

    ((sql, params),) = cursor.executed
    assert " ".join(sql.split()) == (
        "select game_id, title, steam_appid, platform, playtime_minutes "
        "from owned_games where user_id = %s "
        "order by playtime_minutes desc, title nulls last"
    )
    assert params == (str(user),)
    assert [(i.title, i.platform) for i in items] == [("Rust", "xbox")]
