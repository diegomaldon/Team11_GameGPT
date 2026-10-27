"""Write sample embedding documents for a second team member to review (TM11-38).

Builds the per-game document (api/services/game_document.py) for a spread of
games and writes them to a Markdown file with a review checklist and sign-off.
The sample is every Nth game in title order, so it covers the catalogue rather
than its first page, and the same catalogue always gives the same sample.

Usage (from the repo root, with the venv active):
    python scripts/sample_game_documents.py                 # from scripts/fixtures/games.json
    python scripts/sample_game_documents.py --from-db       # from public.games in DATABASE_URL
    python scripts/sample_game_documents.py --count 20 --out artifacts/sprint6/tm11-38/sample-documents.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.game_document import TEMPLATE_VERSION, build_game_document  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "games.json"
DEFAULT_OUT = Path("artifacts") / "sprint6" / "tm11-38" / "sample-documents.md"
DEFAULT_COUNT = 20

CHECKLIST = [
    "Reads like a description of what playing the game feels like.",
    "Genres and tags match the game; nothing obviously wrong or missing.",
    "No HTML, markup, store boilerplate or repeated words left in.",
    "The description is about the game, not a sale, bundle or patch note.",
]


def pick_sample(games: Sequence[Mapping[str, Any]], count: int) -> list[Mapping[str, Any]]:
    """`count` games spread evenly across the catalogue in title order."""
    ordered = sorted(games, key=lambda g: str(g.get("title") or "").casefold())
    if len(ordered) <= count:
        return ordered
    step = len(ordered) / count
    return [ordered[int(n * step)] for n in range(count)]


def render(games: Sequence[Mapping[str, Any]], source: str) -> str:
    lines = [
        f"# TM11-38 sample embedding documents (template {TEMPLATE_VERSION})",
        "",
        f"{len(games)} documents built by `api/services/game_document.py` from {source}.",
        "The template is described in `docs/embedding-documents.md`.",
        "",
        "## How to review",
        "",
        "For each document, tick it if all of these hold, or write what is wrong in Notes:",
        "",
        *[f"- {item}" for item in CHECKLIST],
        "",
        "| # | Game | OK | Notes |",
        "|---|------|----|-------|",
        *[f"| {n} | {g['title']} | [ ] | |" for n, g in enumerate(games, start=1)],
        "",
        "**Reviewed by:** ____________________  **Date:** ____________",
        "",
        "## Documents",
        "",
    ]
    for n, game in enumerate(games, start=1):
        lines += [f"### {n}. {game['title']}", "", "```text", build_game_document(game), "```", ""]
    return "\n".join(lines)


def load_fixture() -> list[dict[str, Any]]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


async def load_db() -> list[dict[str, Any]]:
    from api.db import has_db, repositories

    if not has_db():
        raise SystemExit("sample_game_documents: DATABASE_URL is not set; drop --from-db to use the fixture.")
    # Any model name works: only the games' own fields are used here.
    return await repositories.list_games_with_document_hash("sample")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-db", action="store_true", help="read public.games instead of the fixture")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.from_db:
        games, source = asyncio.run(load_db()), "public.games"
    else:
        games, source = load_fixture(), "`scripts/fixtures/games.json`"

    sample = pick_sample(games, args.count)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(sample, source) + "\n", encoding="utf-8")
    print(f"sample_game_documents: wrote {len(sample)} documents to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
