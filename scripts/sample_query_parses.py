"""Write what QueryParser extracts from a set of sample queries (TM11-62).

Parses each query against the seed catalogue (scripts/fixtures/games.json) and
writes a Markdown table of the signals, so the rules can be reviewed without
running the API. Offline: no database, no model. The same parser and catalogue
always give the same file.

Usage (from the repo root, with the venv active):
    python scripts/sample_query_parses.py
    python scripts/sample_query_parses.py --out artifacts/sprint8/tm11-62-query-parses.md
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.query_parser import (  # noqa: E402
    PARSER_VERSION,
    ParsedQuery,
    TitleIndex,
    parse_query,
)
from api.services.title_matching import CatalogueGame  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "games.json"
DEFAULT_OUT = Path("artifacts") / "sprint8" / "tm11-62-query-parses.md"

SAMPLE_QUERIES = [
    "rpg",
    "cozy",
    "Hades",
    "horror",
    "Something like Hades and Dead Cells, but more relaxing",
    "A cozy farming sim like Stardew Valley that I can play on Xbox, nothing too scary",
    "not a shooter, but a strategy game I can play co-op with friends on Steam",
    "like skyrim but on pc",
    "dark souls 3 but easier",
    "games like Moonfall Saga with good music",
    "I really like rust",
    "an epic adventure",
    "something funny for a party night, no competitive stuff",
    "I don't like shooters",
    "a game like Celeste, nothing like Dark Souls 3",
    (
        "I loved Hollow Knight's art and the way exploring slowly opened up the map. "
        "Looking for a metroidvania that is not too difficult and has a great story, "
        "something emotional like Ori and the Blind Forest or Celeste. I mostly play "
        "on my Steam Deck in bed, so nothing too scary or fast-paced, please!"
    ),
]


def load_index() -> TitleIndex:
    games = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    # Fixture rows have no ids; stable ones keep the output identical run to run.
    return TitleIndex(
        CatalogueGame(uuid.uuid5(uuid.NAMESPACE_URL, g["title"]), g["title"]) for g in games
    )


def _cell(values) -> str:
    values = list(values)
    return ", ".join(values) if values else "—"


def render(rows: list[tuple[str, ParsedQuery]], catalogue_size: int) -> str:
    lines = [
        "# TM11-62 sample query parses",
        "",
        f"Parser `{PARSER_VERSION}` against the seed catalogue ({catalogue_size} games), "
        "written by `scripts/sample_query_parses.py`. Excluded signals are prefixed "
        "with `not`.",
        "",
        "| Query | Genres | Moods | Platforms | Reference titles | Unrecognised |",
        "|---|---|---|---|---|---|",
    ]
    for query, p in rows:
        genres = list(p.genres) + [f"not {g}" for g in p.excluded_genres]
        moods = list(p.moods) + [f"not {m}" for m in p.excluded_moods]
        platforms = list(p.platforms) + [f"not {x}" for x in p.excluded_platforms]
        references = [r.title for r in p.reference_titles] + [
            f"not {r.title}" for r in p.excluded_reference_titles
        ]
        shown = query if len(query) <= 90 else query[:87] + "..."
        lines.append(
            f"| {shown} | {_cell(genres)} | {_cell(moods)} | {_cell(platforms)} | "
            f"{_cell(references)} | "
            f"{_cell(p.unrecognised_references)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    index = load_index()
    rows = [(q, parse_query(q, index)) for q in SAMPLE_QUERIES]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(rows, len(index)), encoding="utf-8")
    print(f"wrote {len(rows)} parses to {args.out}")


if __name__ == "__main__":
    main()
