#!/usr/bin/env python3
"""Record a GetOwnedGames fixture from the live Steam API (TM11-46 AC-04).

AC-04 asks for a *recorded* fixture, so the file under
`api/tests/fixtures/steam/` should come from a real call rather than be written
by hand. This captures one.

    export STEAM_API_KEY=...            # steamcommunity.com/dev/apikey
    python3 scripts/record_steam_fixture.py 76561197960287930

    # see what would be written, without touching the file
    python3 scripts/record_steam_fixture.py 76561197960287930 --dry-run

    # capture the private-profile shape from an account you have set to private
    python3 scripts/record_steam_fixture.py 7656119XXXXXXXXXX --out private_profile.json

Stdlib only, so it runs with a bare `python3` and no virtualenv.

The key never reaches the fixture: it travels in the request query string, and
only `response` is copied out of the reply. The script refuses to write a file
containing the key as a final backstop.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STEAM_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "api" / "tests" / "fixtures" / "steam"


def fetch(api_key: str, steam_id: str, timeout: float = 15.0) -> dict:
    query = urllib.parse.urlencode(
        {
            "key": api_key,
            "steamid": steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        }
    )
    try:
        with urllib.request.urlopen(f"{STEAM_URL}?{query}", timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Never print exc.url / exc.reason blindly — the URL carries the key.
        raise SystemExit(f"Steam returned HTTP {exc.code}. Check STEAM_API_KEY.") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach Steam: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Steam sent a non-JSON body: {exc}") from exc


def describe(payload: dict) -> str:
    response = payload.get("response")
    if not isinstance(response, dict) or "game_count" not in response:
        return (
            "PRIVATE profile — Steam returned {'response': {}} with HTTP 200.\n"
            "  This is the shape private_profile.json records. If you expected a\n"
            "  library, set Profile -> Edit Profile -> Privacy Settings -> both\n"
            "  'My profile' and 'Game details' to Public."
        )
    games = response.get("games") or []
    if not games:
        return "PUBLIC but empty — game_count is 0 and there is no games array."
    played = [g for g in games if g.get("playtime_forever")]
    top = max(games, key=lambda g: g.get("playtime_forever") or 0)
    return (
        f"PUBLIC — game_count={response.get('game_count')}, "
        f"{len(games)} entries, {len(played)} with playtime.\n"
        f"  Most played: {top.get('name')!r} "
        f"({(top.get('playtime_forever') or 0) // 60}h)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("steam_id", help="a 17-digit steamID64")
    ap.add_argument("--out", default="owned_games.json",
                    help="filename inside api/tests/fixtures/steam/")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the summary and write nothing")
    args = ap.parse_args(argv)

    api_key = os.environ.get("STEAM_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("STEAM_API_KEY is not set. Get one at steamcommunity.com/dev/apikey")

    steam_id = args.steam_id.strip()
    if len(steam_id) != 17 or not steam_id.isdigit():
        raise SystemExit(f"{steam_id!r} is not a 17-digit steamID64.")

    payload = fetch(api_key, steam_id)
    print(describe(payload))

    # Keep only `response`. Steam does not echo the key, but copying one field
    # is a guarantee rather than a hope.
    fixture = {"response": payload.get("response", {})}
    text = json.dumps(fixture, indent=2, sort_keys=False) + "\n"

    if api_key in text:  # belt and braces
        raise SystemExit("Refusing to write: the API key appears in the response body.")

    if args.dry_run:
        print("\n--- dry run, nothing written ---")
        print(text[:600] + ("…" if len(text) > 600 else ""))
        return 0

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / args.out
    path.write_text(text, encoding="utf-8")
    print(f"\nWrote {path.relative_to(Path.cwd())} ({len(text)} bytes)")
    print("Re-run the tests:  python -m pytest api/tests/test_steam_client.py -q")
    return 0


if __name__ == "__main__":
    sys.exit(main())
