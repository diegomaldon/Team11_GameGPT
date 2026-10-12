"""POST /api/library/csv/preview and /commit: the HTTP contract (TM11-55).

The browser branches on `detail.error` and shows `detail.message` as is, so
both must be stable and must never leak internals. The DB layer is faked.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.db import repositories
from api.main import create_app

HADES = uuid4()


@pytest.fixture
def client(monkeypatch) -> TestClient:
    async def list_catalogue_games():
        return [{"game_id": HADES, "title": "Hades", "steam_appid": None}]

    async def list_owned_game_ids(user_id, platform):
        return set()

    async def add_owned_games(user_id, platform, games):
        return len(games)

    async def record_library_import(user_id, platform, source, report):
        return uuid4()

    monkeypatch.setattr(repositories, "list_catalogue_games", list_catalogue_games)
    monkeypatch.setattr(repositories, "list_owned_game_ids", list_owned_game_ids)
    monkeypatch.setattr(repositories, "add_owned_games", add_owned_games)
    monkeypatch.setattr(repositories, "record_library_import", record_library_import)
    return TestClient(create_app(), raise_server_exceptions=False)


def _preview(client: TestClient, **body):
    return client.post("/api/library/csv/preview", json={"platform": "epic", **body})


def _commit(client: TestClient, **body):
    return client.post("/api/library/csv/commit", json={"platform": "epic", **body})


def test_preview_returns_per_row_results(client):
    resp = _preview(client, csv_text="title\nHades\nNope\n")
    assert resp.status_code == 200
    body = resp.json()
    assert [(r["row_number"], r["status"]) for r in body["rows"]] == [
        (2, "matched"), (3, "unmatched"),
    ]
    assert (body["matched"], body["needs_review"], body["skipped"]) == (1, 1, 0)


def test_commit_reports_what_changed(client):
    resp = _commit(client, csv_text="title\nHades\nNope\n", excluded_rows=[])
    assert resp.status_code == 200
    body = resp.json()
    assert (body["added"], body["needs_review"], body["skipped"]) == (1, 1, 0)
    assert body["import_id"]


@pytest.mark.parametrize("route", ["preview", "commit"])
def test_malformed_file_is_a_422_with_a_useful_message(client, route):
    body = {"platform": "epic", "csv_text": "name\nx\n"}
    resp = client.post(f"/api/library/csv/{route}", json=body)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "missing_title_column"
    assert "title" in detail["message"]


def test_stale_review_is_a_422(client):
    resp = _commit(client, csv_text="title\nHades\n", excluded_rows=[50])
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "review_mismatch"


@pytest.mark.parametrize("platform", ["playstation", "STEAM", "", "steam; drop table owned_games"])
def test_only_supported_platforms_are_accepted(client, platform):
    resp = client.post(
        "/api/library/csv/preview", json={"platform": platform, "csv_text": "title\nHades\n"}
    )
    assert resp.status_code == 422


def test_text_over_the_limit_is_refused_before_parsing(client):
    from api.services.library_csv import MAX_CSV_BYTES

    resp = _preview(client, csv_text="x" * (MAX_CSV_BYTES + 1))
    assert resp.status_code == 422


def test_too_many_excluded_rows_is_refused(client):
    from api.services.library_csv import MAX_CSV_ROWS

    resp = _commit(client, csv_text="title\nHades\n", excluded_rows=list(range(MAX_CSV_ROWS + 1)))
    assert resp.status_code == 422


def test_db_failure_is_a_503_that_leaks_nothing(client, monkeypatch):
    async def broken():
        raise RuntimeError("psycopg: connection to 10.0.0.5 failed, password=hunter2")

    monkeypatch.setattr(repositories, "list_catalogue_games", broken)
    resp = _preview(client, csv_text="title\nHades\n")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "csv_import_failed"
    assert "psycopg" not in resp.text and "hunter2" not in resp.text
