"""Write the API's OpenAPI contract to openapi.json at the repo root (TM11-21).

openapi.json is what the web app's types are generated from (`npm run gen:api`),
so it has to match the routes the API actually serves. Run this after changing
a route or a model in api/models/schemas.py, then regenerate the web types:

    python scripts/export_openapi.py
    cd web && npm run gen:api

`--check` writes nothing and exits 1 if openapi.json is out of date.
api/tests/test_api_contract.py runs the same comparison in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import create_app  # noqa: E402

OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"


def current_contract() -> dict[str, Any]:
    return create_app().openapi()


def render(contract: dict[str, Any]) -> str:
    return json.dumps(contract, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if openapi.json is stale")
    args = parser.parse_args()

    text = render(current_contract())
    if args.check:
        if OPENAPI_PATH.read_text(encoding="utf-8") != text:
            print("openapi.json is out of date. Run: python scripts/export_openapi.py")
            return 1
        print("openapi.json is up to date.")
        return 0

    OPENAPI_PATH.write_text(text, encoding="utf-8")
    print(f"wrote {OPENAPI_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
