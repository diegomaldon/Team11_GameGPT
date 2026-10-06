"""LibrarySyncService runs every import through title matching.

The DB layer and the Steam hop are both faked, so this runs offline with no
DATABASE_URL and no STEAM_API_KEY.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from api.config import Settings
from api.db import repositories
from api.services.library_sync import LibrarySyncService

pytestmark = pytest.mark.asyncio

USER = UUID("00000000-0000-0000-0000-000000000001")
PORTAL, WITCHER = uuid4(), uuid4()


@pytest.fixture
def fake_db(monkeypatch):
    calls: dict = {}

    async def list_catalogue_games():
        return [
            {"game_id": PORTAL, "title": "Portal 2", "steam_appid": None},
            {"game_id": WITCHER, "title": "The Witcher 3: Wild Hunt", "steam_appid": None},
        ]

    async def import_owned_games(user_id, rows, platform="steam", **kwargs):
        calls["owned"] = list(rows)
        return len(rows), []

    async def record_library_import(user_id, platform, source, report):
        calls["report"] = report
        calls["source"] = source
        return uuid4()

    async def count_owned_games(user_id):
        return 0

    monkeypatch.setattr(repositories, "list_catalogue_games", list_catalogue_games)
    monkeypatch.setattr(repositories, "import_owned_games", import_owned_games)
    monkeypatch.setattr(repositories, "record_library_import", record_library_import)
    monkeypatch.setattr(repositories, "count_owned_games", count_owned_games)
    return calls


def _steam_client(games: list[dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        # game_count matters: without it Steam is saying the profile is private.
        return httpx.Response(200, json={"response": {"game_count": len(games), "games": games}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_steam_import_matches_records_and_reports(fake_db):
    client = _steam_client(
        [
            {"appid": 620, "name": "Portal 2™"},
            {"appid": 292030, "name": "The Witcher® 3: Wild Hunt - Game of the Year Edition"},
            {"appid": 999999, "name": "Obscure Indie"},
        ]
    )
    service = LibrarySyncService(Settings(steam_api_key="test-key"), http_client=client)

    resp = await service.sync(USER, "76561197960287930")

    assert resp.source == "steam"
    assert resp.synced == 3
    assert resp.matched == 2
    assert resp.unmatched == 1
    assert resp.match_rate == pytest.approx(2 / 3, abs=1e-4)
    assert resp.import_id is not None

    by_appid = {r["steam_appid"]: r["game_id"] for r in fake_db["owned"]}
    assert by_appid == {620: PORTAL, 292030: WITCHER, 999999: None}

    report = fake_db["report"]
    assert report.counts_by_method()["normalised"] == 1
    assert report.counts_by_method()["edition"] == 1
    assert [u.imported.title for u in report.unmatched] == ["Obscure Indie"]
    assert report.unmatched[0].reason == "no_match"


async def test_fallback_import_is_matched_too(fake_db):
    resp = await LibrarySyncService(Settings()).sync(USER, "ignored")

    assert resp.source == "seed"
    assert fake_db["source"] == "seed"
    # Portal 2 and The Witcher 3 are in the fake catalogue; the other two are not.
    assert resp.matched == 2
    assert resp.unmatched == 2
    assert resp.match_rate == 0.5
