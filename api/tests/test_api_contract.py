"""The API contract the frontend builds against (TM11-21).

openapi.json is the source of the web app's types (`npm run gen:api`), so a
route or model change that isn't exported to it leaves the frontend building
against a contract the API no longer serves. This pins openapi.json to the app.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "export_openapi.py"


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
