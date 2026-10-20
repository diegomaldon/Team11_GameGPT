"""POST /api/library/xbox and XboxImportService (TM11-56).

One test group per acceptance criterion. The DB layer is faked with an
in-memory owned_games table that enforces the same keys as the real one: one
row per (user, platform, external_id), and one row per (user, platform, game)
for rows without a steam_appid (TM11-55's manual-game index).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.config import get_settings
from api.db import repositories
from api.main import create_app
from api.models import XboxTitle
from api.models.schemas import XBOX_IMPORT_MAX_TITLES
from api.services.xbox_import import (
    XboxImportService,
    distinct_titles,
    plan_xbox_import,
)

HALO = uuid4()
FORZA = uuid4()
PORTAL_2 = uuid4()
CATALOGUE = [
    {"game_id": HALO, "title": "Halo Infinite", "steam_appid": 1240440},
    {"game_id": FORZA, "title": "Forza Horizon 5", "steam_appid": 1551360},
    {"game_id": PORTAL_2, "title": "Portal 2", "steam_appid": 620},
]

HISTORY = [
    {"title_id": "2043073184", "name": "Halo Infinite"},
    {"title_id": "2030093255", "name": "Forza Horizon 5 Premium Edition"},
    {"title_id": "1144039928", "name": "Portal 2™"},
    {"title_id": "1915865634", "name": "Some Indie Nobody Catalogued"},
]


class FakeOwnedGames:
    """owned_games for one user, with the real table's unique keys."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.reports: list[tuple[UUID, str, str, object]] = []
        self.fail_write = False

    def add(self, platform: str, game_id: UUID | None, title: str,
            external_id: str | None = None) -> dict:
        row = {"id": uuid4(), "platform": platform, "game_id": game_id,
               "title": title, "external_id": external_id}
        self.rows.append(row)
        return row

    def xbox_rows(self) -> list[dict]:
        return [r for r in self.rows if r["platform"] == "xbox"]

    def check_keys(self) -> None:
        externals = [(r["platform"], r["external_id"]) for r in self.rows if r["external_id"]]
        games = [(r["platform"], r["game_id"]) for r in self.rows if r["game_id"]]
        assert len(externals) == len(set(externals)), "external_id key violated"
        assert len(games) == len(set(games)), "manual-game key violated"


@pytest.fixture
def owned(monkeypatch) -> FakeOwnedGames:
    db = FakeOwnedGames()

    async def list_catalogue_games():
        return CATALOGUE

    async def list_platform_owned_rows(user_id, platform):
        return [
            {"id": r["id"], "game_id": r["game_id"], "external_id": r["external_id"]}
            for r in db.rows if r["platform"] == platform
        ]

    async def apply_xbox_import(user_id, inserts, updates):
        if db.fail_write:
            raise RuntimeError("connection reset by peer at db.internal:5432")
        before = [dict(r) for r in db.rows]
        try:
            for external_id, title, game_id in inserts:
                hit = next((r for r in db.xbox_rows() if r["external_id"] == external_id), None)
                if hit:
                    hit.update(title=title, game_id=game_id)
                else:
                    db.add("xbox", game_id, title, external_id)
            for row_id, title, game_id in updates:
                row = next(r for r in db.rows if r["id"] == row_id)
                row.update(title=title, game_id=game_id)
            db.check_keys()
        except AssertionError:
            db.rows = before  # one transaction: a violated key rolls everything back
            raise

    async def record_library_import(user_id, platform, source, report):
        db.reports.append((user_id, platform, source, report))
        return uuid4()

    monkeypatch.setattr(repositories, "list_catalogue_games", list_catalogue_games)
    monkeypatch.setattr(repositories, "list_platform_owned_rows", list_platform_owned_rows)
    monkeypatch.setattr(repositories, "apply_xbox_import", apply_xbox_import)
    monkeypatch.setattr(repositories, "record_library_import", record_library_import)
    return db


@pytest.fixture
def client(owned) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _import(client: TestClient, titles=HISTORY):
    return client.post("/api/library/xbox", json={"titles": titles})


# ── AC: owned titles written to owned_games with platform attribution ──


def test_every_title_is_written_as_an_xbox_row(client, owned):
    resp = _import(client)

    assert resp.status_code == 200
    assert resp.json()["added"] == len(HISTORY)
    assert {r["platform"] for r in owned.rows} == {"xbox"}
    assert {r["external_id"] for r in owned.rows} == {t["title_id"] for t in HISTORY}


def test_rows_keep_the_title_as_xbox_spells_it(client, owned):
    _import(client)
    assert {r["title"] for r in owned.rows} == {t["name"] for t in HISTORY}


def test_the_import_is_recorded_against_xbox(client, owned):
    _import(client)
    [(user_id, platform, source, report)] = owned.reports
    assert user_id == UUID(get_settings().dev_user_id)
    assert (platform, source) == ("xbox", "xbox")
    assert report.total == len(HISTORY)


def test_xbox_rows_leave_the_steam_library_alone(client, owned):
    steam = owned.add("steam", PORTAL_2, "Portal 2")
    _import(client)
    assert steam in owned.rows
    assert sum(1 for r in owned.rows if r["platform"] == "steam") == 1


# ── AC: reuses the title matcher ──


def test_titles_are_matched_with_the_shared_title_matcher(client, owned):
    body = _import(client).json()

    by_title = {r["title"]: r["game_id"] for r in owned.rows}
    assert by_title["Halo Infinite"] == HALO
    assert by_title["Portal 2™"] == PORTAL_2  # normalised tier
    assert by_title["Forza Horizon 5 Premium Edition"] == FORZA  # edition tier
    assert body["matched"] == 3
    assert body["match_rate"] == 0.75


def test_unmatched_titles_are_kept_and_queued_for_review(client, owned):
    body = _import(client).json()

    [indie] = [r for r in owned.rows if r["title"] == "Some Indie Nobody Catalogued"]
    assert indie["game_id"] is None
    assert body["unmatched"] == 1
    [(_, _, _, report)] = owned.reports
    assert [u.imported.title for u in report.unmatched] == ["Some Indie Nobody Catalogued"]


# ── AC: idempotent on re-run ──


def test_a_second_import_adds_nothing(client, owned):
    _import(client)
    snapshot = sorted((r["external_id"], r["title"], str(r["game_id"])) for r in owned.rows)

    body = _import(client).json()

    assert body["added"] == 0
    assert body["updated"] == len(HISTORY)
    assert sorted((r["external_id"], r["title"], str(r["game_id"])) for r in owned.rows) == snapshot


def test_a_rerun_refreshes_a_renamed_title_in_place(client, owned):
    _import(client)
    renamed = [dict(HISTORY[0], name="Halo Infinite (Campaign)")] + HISTORY[1:]

    _import(client, renamed)

    [row] = [r for r in owned.rows if r["external_id"] == HISTORY[0]["title_id"]]
    assert row["title"] == "Halo Infinite (Campaign)"
    assert len(owned.rows) == len(HISTORY)


def test_a_game_already_added_by_csv_is_not_added_twice(client, owned):
    owned.add("xbox", HALO, "Halo Infinite")  # TM11-55 CSV row: no external_id

    body = _import(client).json()

    assert body["already_owned"] == 1
    assert sum(1 for r in owned.rows if r["game_id"] == HALO) == 1
    owned.check_keys()


def test_the_same_title_listed_twice_is_imported_once(client, owned):
    body = _import(client, HISTORY + [HISTORY[0]]).json()
    assert body["total"] == len(HISTORY)
    assert len(owned.rows) == len(HISTORY)


def test_two_xbox_titles_for_one_game_keep_one_row(client, owned):
    # PC and console builds of one game can have different titleIds.
    pc = {"title_id": "1000000001", "name": "Halo Infinite"}
    body = _import(client, [HISTORY[0], pc]).json()

    assert body["added"] == 1
    assert body["already_owned"] == 1
    owned.check_keys()


# ── errors and validation ──


def test_a_failed_write_is_503_with_a_safe_message(client, owned):
    owned.fail_write = True

    resp = _import(client)

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["error"] == "import_failed"
    assert "unchanged" in detail["message"]
    assert "db.internal" not in resp.text
    assert owned.rows == []


@pytest.mark.parametrize("titles", [
    [{"title_id": "abc", "name": "Halo"}],          # titleIds are decimal
    [{"title_id": "123", "name": ""}],              # blank name
    [{"title_id": "123"}],                          # no name
    [{"title_id": str(i), "name": "x"} for i in range(XBOX_IMPORT_MAX_TITLES + 1)],
])
def test_bad_bodies_are_rejected_before_any_write(client, owned, titles):
    assert _import(client, titles).status_code == 422
    assert owned.rows == []


def test_an_empty_history_imports_nothing_and_succeeds(client, owned):
    body = _import(client, []).json()
    assert body == {**body, "total": 0, "added": 0, "match_rate": 0.0}
    assert owned.rows == []


# ── the plan, without the service ──


def _t(title_id: str, name: str = "x") -> XboxTitle:
    return XboxTitle(title_id=title_id, name=name)


def test_plan_keeps_a_rows_old_link_when_its_game_moved_to_another_row():
    existing_xbox = {"id": uuid4(), "game_id": None, "external_id": "1"}
    csv_row = {"id": uuid4(), "game_id": HALO, "external_id": None}

    plan = plan_xbox_import([existing_xbox, csv_row], [(_t("1", "Halo Infinite"), HALO)])

    assert plan.updates == [(existing_xbox["id"], "Halo Infinite", None)]
    assert plan.inserts == []


def test_plan_inserts_new_titles_and_updates_known_ones():
    known = {"id": uuid4(), "game_id": FORZA, "external_id": "2"}

    plan = plan_xbox_import([known], [(_t("1"), HALO), (_t("2"), FORZA), (_t("3"), None)])

    assert [i[0] for i in plan.inserts] == ["1", "3"]
    assert plan.updates == [(known["id"], "x", FORZA)]
    assert plan.already_owned == []


def test_distinct_titles_keeps_the_first_of_each_title_id():
    titles = [_t("1", "a"), _t("2", "b"), _t("1", "c")]
    assert [t.name for t in distinct_titles(titles)] == ["a", "b"]


def test_a_missing_report_does_not_fail_the_import(owned, monkeypatch):
    async def broken_report(*args):
        raise RuntimeError("library_imports does not exist")

    monkeypatch.setattr(repositories, "record_library_import", broken_report)
    titles = [XboxTitle(**t) for t in HISTORY]

    result = asyncio.run(XboxImportService().import_titles(uuid4(), titles))

    assert result.added == len(HISTORY)
    assert result.import_id is None


# ── the SQL ──


class _RecordingDb:
    def __init__(self) -> None:
        self.statements: list[tuple[str, list]] = []
        self.transactions = 0

    def connection(self):
        db = self

        class Cursor:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def executemany(self, sql, params):
                db.statements.append((sql, list(params)))

        class Conn:
            def cursor(self):
                return Cursor()

            @asynccontextmanager
            async def transaction(self):
                db.transactions += 1
                yield

        @asynccontextmanager
        async def connect():
            yield Conn()

        return connect()


def test_apply_writes_platform_xbox_in_one_transaction(monkeypatch):
    db = _RecordingDb()
    monkeypatch.setattr(repositories, "connection", db.connection)
    row_id = uuid4()

    asyncio.run(repositories.apply_xbox_import.__wrapped__(
        uuid4(), [("1", "Halo Infinite", HALO)], [(row_id, "Forza", None)],
    ))

    assert db.transactions == 1
    [(insert_sql, insert_rows), (update_sql, update_rows)] = db.statements
    assert "values (%s, 'xbox', %s, %s, %s)" in insert_sql
    assert "on conflict (user_id, platform, external_id)" in insert_sql
    assert insert_rows[0][1:] == ("1", "Halo Infinite", str(HALO))
    assert update_rows == [("Forza", None, str(row_id), update_rows[0][3])]
