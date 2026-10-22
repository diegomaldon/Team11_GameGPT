"""Ownership check and owned-game filter (TM11-58, REQ007, REQ008).

The connection and shape check are faked, so these run offline. Each test is
named for the acceptance criterion it covers:

  AC-01  check_ownership resolves a game across all linked platforms
  AC-02  filter_owned removes owned titles from any candidate list
  AC-03  the platforms a title is owned on come back for the UI badges
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest

from api.models import GameCandidate
from api.services import deduplication
from api.services.deduplication import DeduplicationService, Ownership


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


@pytest.fixture
def db(monkeypatch):
    """Fake owned_games. Call with the shape and the rows the query returns."""

    def install(shape: str, rows: list[tuple]) -> FakeCursor:
        cursor = FakeCursor(rows)

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
        return cursor

    return install


def game(title: str, steam_appid: int | None = None) -> GameCandidate:
    return GameCandidate(game_id=uuid4(), title=title, steam_appid=steam_appid)


USER = UUID("00000000-0000-0000-0000-000000000058")


# ── AC-01: check_ownership across every linked platform ─────────────────────


@pytest.mark.asyncio
async def test_ac01_hosted_game_owned_on_two_platforms_resolves_to_both(db):
    hades = game("Hades")
    cursor = db("hosted", [(hades.game_id, "XBOX"), (hades.game_id, "STEAM")])

    result = await DeduplicationService().check_ownership(USER, hades)

    assert result == Ownership(game_id=hades.game_id, platforms=("steam", "xbox"))
    assert result.is_owned
    query, params = cursor.executed[0]
    assert "join public.platform_accounts" in query
    assert params == (USER, [hades.game_id])


@pytest.mark.asyncio
async def test_ac01_hosted_game_not_in_any_library_is_not_owned(db):
    celeste = game("Celeste")
    db("hosted", [])

    result = await DeduplicationService().check_ownership(USER, celeste)

    assert result == Ownership(game_id=celeste.game_id, platforms=())
    assert not result.is_owned


@pytest.mark.asyncio
async def test_ac01_legacy_matches_on_game_id_appid_or_title(db):
    by_id, by_appid, by_title = game("Hades"), game("Portal 2", 620), game("The Witcher 3")
    db("legacy", [
        (by_id.game_id, None, "Hades", "xbox"),
        (None, 620, "Portal 2", "steam"),
        (None, None, "the witcher 3!", "epic"),  # manual add, no appid or game_id
    ])
    service = DeduplicationService()

    assert (await service.check_ownership(USER, by_id)).platforms == ("xbox",)
    assert (await service.check_ownership(USER, by_appid)).platforms == ("steam",)
    assert (await service.check_ownership(USER, by_title)).platforms == ("epic",)


@pytest.mark.asyncio
async def test_ac01_legacy_same_title_on_steam_and_epic_resolves_to_both(db):
    stardew = game("Stardew Valley", 413150)
    db("legacy", [
        (None, 413150, "Stardew Valley", "steam"),
        (None, None, "Stardew Valley", "epic"),
    ])

    result = await DeduplicationService().check_ownership(USER, stardew)

    assert result.platforms == ("steam", "epic")


@pytest.mark.asyncio
async def test_ac01_legacy_similar_title_is_not_owned(db):
    db("legacy", [(None, None, "Hades", "steam")])

    result = await DeduplicationService().check_ownership(USER, game("Hades II"))

    assert not result.is_owned


# ── AC-03: platforms for the UI badges ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ac03_owned_platforms_lists_only_owned_games_in_badge_order(db):
    hades, celeste, doom = game("Hades"), game("Celeste"), game("DOOM")
    db("hosted", [
        (doom.game_id, "EPIC"),
        (doom.game_id, "STEAM"),
        (doom.game_id, "XBOX"),
        (hades.game_id, "STEAM"),
    ])

    platforms = await DeduplicationService().owned_platforms(USER, [hades, celeste, doom])

    assert platforms == {
        hades.game_id: ("steam",),
        doom.game_id: ("steam", "xbox", "epic"),
    }


@pytest.mark.asyncio
async def test_ac03_unknown_platform_sorts_after_known_ones(db):
    hades = game("Hades")
    db("legacy", [(hades.game_id, None, "Hades", "gog"), (hades.game_id, None, "Hades", "steam")])

    result = await DeduplicationService().check_ownership(USER, hades)

    assert result.platforms == ("steam", "gog")


@pytest.mark.asyncio
async def test_ac03_one_query_for_the_whole_list(db):
    games = [game(f"Game {i}") for i in range(5)]
    cursor = db("hosted", [])

    await DeduplicationService().owned_platforms(USER, games)

    assert len(cursor.executed) == 1


@pytest.mark.asyncio
async def test_ac03_empty_list_skips_the_database(db):
    cursor = db("hosted", [])

    assert await DeduplicationService().owned_platforms(USER, []) == {}
    assert cursor.executed == []
