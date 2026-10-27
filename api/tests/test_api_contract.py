"""The API contract the frontend builds against (TM11-21).

openapi.json is the source of the web app's types (`npm run gen:api`), so a
route or model change that isn't exported to it leaves the frontend building
against a contract the API no longer serves. This pins openapi.json to the app,
checks docs/API.md documents every route, and pins the four error shapes the
docs promise.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "export_openapi.py"
API_DOC = ROOT / "docs" / "API.md"


def load_script():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export_openapi = load_script()


# ── openapi.json matches the app ────────────────────────────────────────────


def test_committed_openapi_json_matches_the_app():
    committed = json.loads(export_openapi.OPENAPI_PATH.read_text(encoding="utf-8"))

    assert committed == export_openapi.current_contract(), (
        "openapi.json is out of date. Run: python scripts/export_openapi.py"
    )


def test_committed_openapi_json_is_in_the_exported_format():
    # Byte for byte, so a hand edit or a different exporter shows up as a diff
    # in review instead of reformatting the whole file.
    committed = export_openapi.OPENAPI_PATH.read_text(encoding="utf-8")

    assert committed == export_openapi.render(export_openapi.current_contract())


def test_every_api_route_is_in_openapi_json():
    committed = json.loads(export_openapi.OPENAPI_PATH.read_text(encoding="utf-8"))
    routes = {
        route.path
        for route in export_openapi.create_app().routes
        if route.path.startswith("/api/")
    }

    assert routes == set(committed["paths"])


# ── docs/API.md documents every route ───────────────────────────────────────

# "## `GET /api/library`", or "## `GET /api/games/{game_id}` (planned)" for a
# contract the frontend can build against before the route exists.
HEADING = re.compile(r"^## `(GET|POST|PUT|PATCH|DELETE) (/api/\S+)`( \(planned\))?$", re.M)


def documented() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    live, planned = set(), set()
    for method, path, is_planned in HEADING.findall(API_DOC.read_text(encoding="utf-8")):
        (planned if is_planned else live).add((method, path))
    return live, planned


def served() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in export_openapi.create_app().routes
        if route.path.startswith("/api/")
        for method in getattr(route, "methods", set()) - {"HEAD"}
    }


def test_every_route_has_a_section_in_api_md():
    live, _ = documented()

    assert served() - live == set(), "add a section to docs/API.md for each of these"


def test_every_section_in_api_md_is_a_route():
    live, _ = documented()

    assert live - served() == set(), "documented but not served; mark it (planned) or remove it"


def test_a_planned_contract_is_not_served_yet():
    # Once the route exists, the "(planned)" marker has to come off.
    _, planned = documented()

    assert planned & served() == set()


def test_every_documented_error_code_exists_in_the_api():
    doc = API_DOC.read_text(encoding="utf-8")
    table = doc[doc.index("**Error codes**"):doc.index("A background sync")]
    codes = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", table))
    source = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "api").rglob("*.py")
                       if "tests" not in p.parts)

    missing = {code for code in codes if f'"{code}"' not in source}

    assert codes and missing == set()


# ── the four error shapes ───────────────────────────────────────────────────


@pytest.fixture
def client():
    app = export_openapi.create_app()

    @app.get("/api/_contract_boom")
    async def boom():
        raise RuntimeError("the cause, which must not reach the client")

    return TestClient(app, raise_server_exceptions=False)


def test_a_handled_error_is_a_detail_object(client):
    resp = client.get(f"/api/library/sync/jobs/{uuid4()}")

    assert resp.status_code == 404
    assert resp.json() == {"detail": {"error": "job_not_found", "message": "No such sync job."}}
    assert resp.headers["x-request-id"]


def test_a_request_validation_error_is_a_detail_list(client):
    resp = client.post("/api/recommend", json={})

    assert resp.status_code == 422
    [problem] = resp.json()["detail"]
    assert problem["loc"] == ["body", "query"]
    assert {"type", "msg"} <= problem.keys()


def test_an_oversized_body_is_a_handled_413(client):
    resp = client.post(
        "/api/library/csv/preview",
        content=b"x" * 4_000_001,
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413
    assert resp.json()["detail"]["error"] == "request_too_large"


def test_an_unknown_route_is_a_detail_string(client):
    resp = client.get("/api/no-such-route")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_an_unexpected_error_is_a_top_level_500_without_the_cause(client):
    resp = client.get("/api/_contract_boom", headers={"x-request-id": "contract-test"})

    assert resp.status_code == 500
    body = resp.json()
    assert body == {
        "error": "internal_error",
        "message": "Something went wrong. Quote this id if you report it.",
        "request_id": "contract-test",
    }
    assert resp.headers["x-request-id"] == "contract-test"
    assert "cause" not in resp.text
