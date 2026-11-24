"""GET /api/games/{game_id}: one game for the detail panel (TM11-78, REQ009).

AC: the panel shows description, genre tags, platforms, and user and critic
scores; missing fields render as unavailable rather than blank or broken. The
endpoint is what fills the panel from any surface, so these pin the contract in
docs/API.md on both database shapes: every field comes back, a missing one
comes back empty (never guessed), and the 404/422/503 a client branches on. The
database is faked; the hosted read was also checked by hand against hosted.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.main import create_app
from api.models import GameDetail
from api.services.deduplication import DeduplicationService

RUST = UUID("e8d9b506-4699-4983-8699-7d1684827cba")


class _FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, params):
        self.executed.append((sql, params))

    async def fetchone(self):
        return self._row

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
    def install(shape: str, row: tuple | None) -> _FakeCursor:
        cursor = _FakeCursor(row)

        @asynccontextmanager
        async def connection():
            yield _FakeConnection(cursor)

        async def catalogue_shape():
            return shape

        monkeypatch.setattr(repositories, "connection", connection)
        monkeypatch.setattr(repositories, "catalogue_shape", catalogue_shape)
        return cursor

    return install


def _hosted_row(**overrides) -> tuple:
    row = {
        "game_id": RUST,
        "title": "Rust",
        "description": "A brutal multiplayer survival game where trust is the scarcest resource.",
        "genres": ["Survival", "Multiplayer"],
        "tags": ["pvp", "Co-op"],
        "release_date": date(2018, 2, 8),
        "developers": ["Facepunch Studios"],
        "publishers": ["Facepunch Studios"],
        "header_image_url": "https://cdn.example/rust/header.jpg",
        "review_score": 85,
        "critic_score": 69,
        "steam_appid": 252490,
        "platforms": "{STEAM,XBOX}",  # an enum array read as text
        "purchase_links": {"STEAM": "https://store.steampowered.com/app/252490"},
    }
    row.update(overrides)
    return tuple(row.values())


# ── AC: shows description, genre tags, platforms, user and critic scores ──


@pytest.mark.asyncio
async def test_a_hosted_game_comes_back_with_every_panel_field(fake_db):
    cursor = fake_db("hosted", _hosted_row())

    detail = await repositories.get_game_detail(RUST)

    sql, params = cursor.executed[0]
    assert "from public.games where game_id = %s" in sql
    assert params == (str(RUST),)
    assert detail.title == "Rust"
    assert detail.description.startswith("A brutal multiplayer survival game")
    assert detail.genres == ["Survival", "Multiplayer"]
    assert detail.tags == ["pvp", "Co-op"]
    assert detail.available_platforms == ["steam", "xbox"]
    # Stored 0-100; served 0-1 like every other score in the API.
    assert (detail.review_score, detail.critic_score) == (0.85, 0.69)
    assert detail.release_date == date(2018, 2, 8)
    assert detail.developers == ["Facepunch Studios"]
    assert detail.purchase_links == {"steam": "https://store.steampowered.com/app/252490"}
    assert detail.steam_appid == 252490


@pytest.mark.asyncio
async def test_the_local_slice_reads_its_own_columns(fake_db):
    # 0001_init.sql: id not game_id, a 0-1 review score, one developer, and no
    # platforms, critic score, header image or purchase links.
    game_id = uuid4()
    cursor = fake_db("legacy", (game_id, "Hades", "Defy the god of the dead.", ["Roguelike"],
                                [], None, ["Supergiant Games"], [], None, 0.97, None,
                                1145360, [], {}))

    detail = await repositories.get_game_detail(game_id)

    assert "from games where id = %s" in cursor.executed[0][0]
    assert detail.review_score == 0.97
    assert detail.critic_score is None
    assert detail.available_platforms == []
    assert detail.developers == ["Supergiant Games"]


# ── AC: missing fields render as unavailable rather than blank or broken ──


@pytest.mark.asyncio
async def test_missing_fields_come_back_empty_never_guessed(fake_db):
    fake_db("hosted", _hosted_row(description="   ", genres=[], tags=None, release_date=None,
                                  developers=None, publishers=[], header_image_url="",
                                  review_score=None, critic_score=None, steam_appid=None,
                                  platforms=None, purchase_links={}))

    detail = await repositories.get_game_detail(RUST)

    assert detail.description is None  # blank is missing, not an empty paragraph
    assert detail.genres == detail.tags == detail.available_platforms == []
    assert detail.review_score is None and detail.critic_score is None
    assert detail.release_date is None and detail.steam_appid is None
    assert detail.header_image_url is None
    assert detail.developers == detail.publishers == []
    assert detail.purchase_links == {}


@pytest.mark.asyncio
async def test_only_real_links_are_kept_and_scores_stay_in_range(fake_db):
    fake_db("hosted", _hosted_row(review_score=100, critic_score=0,
                                  purchase_links={"EPIC": "javascript:alert(1)", "XBOX": None}))

    detail = await repositories.get_game_detail(RUST)

    assert detail.purchase_links == {}
    assert (detail.review_score, detail.critic_score) == (1.0, 0.0)


@pytest.mark.asyncio
async def test_an_unknown_id_is_none(fake_db):
    fake_db("hosted", None)

    assert await repositories.get_game_detail(uuid4()) is None


# ── HTTP: what the panel branches on ──


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def fake_detail(monkeypatch):
    owned: dict[UUID, tuple[str, ...]] = {}

    def install(result):
        async def get_game_detail(game_id):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(repositories, "get_game_detail", get_game_detail)

    async def owned_platforms(self, user_id, games):
        return {g.game_id: owned[g.game_id] for g in games if g.game_id in owned}

    monkeypatch.setattr(DeduplicationService, "owned_platforms", owned_platforms)
    install.owned = owned
    return install


def test_the_route_returns_the_game_with_where_it_is_owned(fake_detail, client):
    fake_detail(GameDetail(game_id=RUST, title="Rust", genres=["Survival"], review_score=0.85,
                           critic_score=0.69, available_platforms=["steam"]))
    fake_detail.owned[RUST] = ("steam", "xbox")

    res = client.get(f"/api/games/{RUST}")

    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Rust"
    assert (body["review_score"], body["critic_score"]) == (0.85, 0.69)
    assert body["owned_on"] == ["steam", "xbox"]
    assert body["description"] is None  # sent as null, so the panel can say "unavailable"


def test_a_game_the_user_doesnt_own_has_no_owned_platforms(fake_detail, client):
    fake_detail(GameDetail(game_id=RUST, title="Rust"))

    assert client.get(f"/api/games/{RUST}").json()["owned_on"] == []


def test_an_unknown_game_is_a_404_with_a_code(fake_detail, client):
    fake_detail(None)

    res = client.get(f"/api/games/{uuid4()}")

    assert res.status_code == 404
    assert res.json()["detail"]["error"] == "game_not_found"


def test_a_malformed_id_is_a_422(client):
    assert client.get("/api/games/not-a-uuid").status_code == 422


def test_a_failed_read_is_a_503_that_hides_the_cause(fake_detail, client):
    fake_detail(RuntimeError("connection to db.internal:5432 refused"))

    res = client.get(f"/api/games/{uuid4()}")

    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["error"] == "game_detail_failed"
    assert "db.internal" not in detail["message"]


def test_games_search_still_routes_to_the_autocomplete(monkeypatch, client):
    # /games/{game_id} is registered after /games/search, so "search" is never an id.
    async def search_catalogue_games(query, limit):
        return [{"game_id": RUST, "title": "Rust", "steam_appid": 252490}]

    monkeypatch.setattr(repositories, "search_catalogue_games", search_catalogue_games)

    res = client.get("/api/games/search", params={"q": "rus"})

    assert res.status_code == 200
    assert res.json()["items"][0]["title"] == "Rust"
