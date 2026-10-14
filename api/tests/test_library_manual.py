"""GET /api/games/search and POST /api/library/manual (TM11-54).

One test group per acceptance criterion. The DB layer is faked with an
in-memory library that behaves like owned_games_user_platform_manual_game_key:
a second add of the same (user, platform, game) is skipped, never an error.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.db.repositories import _like_pattern
from api.main import create_app

HADES = uuid4()
HADES_II = uuid4()
CELESTE = uuid4()
CATALOGUE = {
    HADES: {"game_id": HADES, "title": "Hades", "steam_appid": 1145360},
    HADES_II: {"game_id": HADES_II, "title": "Hades II", "steam_appid": None},
    CELESTE: {"game_id": CELESTE, "title": "Celeste", "steam_appid": None},
}


class FakeLibrary:
    def __init__(self) -> None:
        self.rows: set[tuple[UUID, str, UUID]] = set()  # (user, platform, game)
        self.searches: list[tuple[str, int]] = []


@pytest.fixture
def library(monkeypatch) -> FakeLibrary:
    lib = FakeLibrary()

    async def search_catalogue_games(query, limit):
        lib.searches.append((query, limit))
        hits = [g for g in CATALOGUE.values() if query.lower() in g["title"].lower()]
        return hits[:limit]

    async def get_catalogue_game(game_id):
        return CATALOGUE.get(game_id)

    async def add_manual_game(user_id, platform, game_id, title):
        key = (user_id, platform, game_id)
        if key in lib.rows:
            return False  # the unique index skipped the row
        lib.rows.add(key)
        return True

    monkeypatch.setattr(repositories, "search_catalogue_games", search_catalogue_games)
    monkeypatch.setattr(repositories, "get_catalogue_game", get_catalogue_game)
    monkeypatch.setattr(repositories, "add_manual_game", add_manual_game)
    return lib


@pytest.fixture
def client(library) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _add(client: TestClient, game_id: UUID, platform: str = "epic"):
    return client.post("/api/library/manual", json={"platform": platform, "game_id": str(game_id)})


class _RecordingDb:
    """A stand-in for api.db.connection() that records the SQL it is sent."""

    def __init__(self, result) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self.result = result

    def connection(self):
        db = self

        class Cursor:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def execute(self, sql, params):
                db.statements.append((sql, params))

            async def fetchone(self):
                return db.result

        class Conn:
            def cursor(self):
                return Cursor()

            async def commit(self):
                pass

        @asynccontextmanager
        async def connect():
            yield Conn()

        return connect()


# ── AC: manual entry with autocomplete against the games table ──


def test_search_returns_catalogue_games(client):
    resp = client.get("/api/games/search", params={"q": "hades"})
    assert resp.status_code == 200
    assert [i["title"] for i in resp.json()["items"]] == ["Hades", "Hades II"]
    assert resp.json()["items"][0] == {
        "game_id": str(HADES), "title": "Hades", "steam_appid": 1145360,
    }


def test_search_under_two_characters_skips_the_database(client, library):
    resp = client.get("/api/games/search", params={"q": " h "})
    assert resp.status_code == 200
    assert resp.json() == {"items": []}
    assert library.searches == []


def test_search_collapses_whitespace_and_passes_the_limit(client, library):
    client.get("/api/games/search", params={"q": "  hades   ii ", "limit": 3})
    assert library.searches == [("hades ii", 3)]


@pytest.mark.parametrize("params", [{"q": "x" * 101}, {"q": "hades", "limit": 0},
                                    {"q": "hades", "limit": 21}, {}])
def test_search_rejects_bad_parameters(client, params):
    assert client.get("/api/games/search", params=params).status_code == 422


def test_like_wildcards_are_escaped():
    assert _like_pattern("100%_off!") == "100!%!_off!!"
    assert _like_pattern("Hades") == "Hades"


def test_add_rejects_a_game_not_in_the_catalogue(client):
    resp = _add(client, uuid4())
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "game_not_found"


# ── AC: entries stored with importMethod MANUAL against the right platform ──


def test_add_stores_the_game_on_the_chosen_platform(client, library):
    resp = _add(client, HADES, platform="xbox")
    assert resp.status_code == 201
    assert resp.json() == {
        "game_id": str(HADES), "title": "Hades", "platform": "xbox", "import_method": "MANUAL",
    }
    assert [(p, g) for (_, p, g) in library.rows] == [("xbox", HADES)]


@pytest.mark.parametrize("platform", ["steam", "playstation", "EPIC", ""])
def test_add_only_accepts_platforms_without_a_library_api(client, platform):
    assert _add(client, HADES, platform=platform).status_code == 422


def test_add_manual_game_writes_import_method_manual(monkeypatch):
    db = _RecordingDb(result=(HADES,))
    monkeypatch.setattr(repositories, "connection", db.connection)
    user = uuid4()

    assert asyncio.run(repositories.add_manual_game(user, "xbox", HADES, "Hades")) is True
    [(sql, params)] = db.statements
    assert "import_method" in sql and "'MANUAL'" in sql
    assert "on conflict do nothing" in sql
    assert params == (str(user), "xbox", str(HADES), "Hades")


# ── AC: duplicate entry prevented ──


def test_adding_the_same_game_twice_is_refused(client, library):
    assert _add(client, HADES).status_code == 201
    resp = _add(client, HADES)
    assert resp.status_code == 409
    assert resp.json()["detail"] == {
        "error": "already_owned",
        "message": "That game is already in your library on this platform.",
    }
    assert len(library.rows) == 1


def test_add_manual_game_reports_a_skipped_duplicate(monkeypatch):
    """The unique index skipped the insert, so RETURNING gave no row."""
    db = _RecordingDb(result=None)
    monkeypatch.setattr(repositories, "connection", db.connection)

    assert asyncio.run(repositories.add_manual_game(uuid4(), "epic", HADES, "Hades")) is False


def test_the_same_game_on_another_platform_is_not_a_duplicate(client, library):
    assert _add(client, HADES, platform="epic").status_code == 201
    assert _add(client, HADES, platform="xbox").status_code == 201
    assert len(library.rows) == 2


# ── AC: works for Epic and for Xbox ──


@pytest.mark.parametrize("platform", ["epic", "xbox"])
def test_add_works_for_epic_and_xbox(client, platform):
    resp = _add(client, CELESTE, platform=platform)
    assert resp.status_code == 201
    assert resp.json()["platform"] == platform


# ── failures stay generic ──


def test_db_failure_on_add_is_a_generic_503(client, monkeypatch):
    async def broken(game_id):
        raise RuntimeError("connection refused to db.internal:5432")

    monkeypatch.setattr(repositories, "get_catalogue_game", broken)
    resp = _add(client, HADES)
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "manual_import_failed"
    assert "db.internal" not in resp.text


def test_db_failure_on_search_is_a_generic_503(client, monkeypatch):
    async def broken(query, limit):
        raise RuntimeError("connection refused to db.internal:5432")

    monkeypatch.setattr(repositories, "search_catalogue_games", broken)
    resp = client.get("/api/games/search", params={"q": "hades"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "search_failed"
    assert "db.internal" not in resp.text
