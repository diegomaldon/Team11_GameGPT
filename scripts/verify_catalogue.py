#!/usr/bin/env python3
"""Check the hosted catalogue after a rebuild (TM11-159). Read-only.

Run after ingest_games.py and embed_catalogue.py, against the same DATABASE_URL:

    python scripts/verify_catalogue.py                  # prints a report, writes the artifact
    python scripts/verify_catalogue.py --min-games 167

Checks, each one an acceptance criterion of TM11-159:

  size          at least --min-games games (default 167, the seed catalogue)
  duplicates    no two games share a steam_appid or a trimmed, case-folded title
  fields        how many games lack a description, genres or steam_appid
  embedded      every game has a vector for the configured EMBEDDING_MODEL, so
                POST /api/search and /api/recommend can return it
  benchmark     every expected and reference title in the TM11-63 benchmark
                (api/fixtures/query_benchmark.json) is a games.title

Field gaps are reported but don't fail the run: the AC says "where available".
Everything else does. Exit 0 when all pass, 1 when any fails, 2 with no database.
Report: artifacts/sprint9/tm11-159-catalogue-check.md (and .json).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "api" / "fixtures" / "query_benchmark.json"
REPORT_DIR = ROOT / "artifacts" / "sprint9"
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # api/config.py default
DEFAULT_MIN_GAMES = 167


@dataclass
class CatalogueCheck:
    model: str
    min_games: int
    games: int = 0
    embedded: int = 0
    missing_description: int = 0
    missing_genres: int = 0
    missing_steam_appid: int = 0
    duplicate_appids: list[int] = field(default_factory=list)
    duplicate_titles: list[str] = field(default_factory=list)
    unembedded_titles: list[str] = field(default_factory=list)
    missing_benchmark_titles: list[str] = field(default_factory=list)
    benchmark_titles: int = 0

    @property
    def checks(self) -> dict[str, bool]:
        return {
            "size": self.games >= self.min_games,
            "duplicates": not self.duplicate_appids and not self.duplicate_titles,
            "embedded": self.games > 0 and self.embedded == self.games,
            "benchmark": not self.missing_benchmark_titles,
        }

    @property
    def ok(self) -> bool:
        return all(self.checks.values())


def benchmark_titles(path: Path = BENCHMARK_PATH) -> set[str]:
    """Every title the benchmark expects to find: expected answers and named references."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    titles: set[str] = set()
    for q in raw["queries"]:
        titles.update(q.get("expected_titles", []))
        titles.update(q.get("reference_titles", []))
    return titles


def evaluate(rows: list[dict], expected: set[str], model: str,
             min_games: int = DEFAULT_MIN_GAMES) -> CatalogueCheck:
    """Score catalogue rows. Each row: title, description, genres, steam_appid, embedded (bool)."""
    c = CatalogueCheck(model=model, min_games=min_games, games=len(rows))
    seen_ids: dict[int, int] = {}
    seen_titles: dict[str, int] = {}
    for r in rows:
        c.embedded += bool(r.get("embedded"))
        if not r.get("embedded"):
            c.unembedded_titles.append(r["title"])
        c.missing_description += not (r.get("description") or "").strip()
        c.missing_genres += not r.get("genres")
        appid = r.get("steam_appid")
        if appid is None:
            c.missing_steam_appid += 1
        else:
            seen_ids[appid] = seen_ids.get(appid, 0) + 1
        key = (r["title"] or "").strip().casefold()
        seen_titles[key] = seen_titles.get(key, 0) + 1
    c.duplicate_appids = sorted(k for k, n in seen_ids.items() if n > 1)
    c.duplicate_titles = sorted(k for k, n in seen_titles.items() if n > 1)
    titles = {r["title"] for r in rows}
    c.missing_benchmark_titles = sorted(expected - titles)
    c.benchmark_titles = len(expected)
    c.unembedded_titles.sort()
    return c


QUERY = """
select g.title, g.description, g.genres, g.steam_appid,
       exists (select 1 from public.game_embeddings e
               where e.game_id = g.game_id and e.model = %s) as embedded
from public.games g
order by g.title
"""


def fetch_rows(dsn: str, model: str) -> list[dict]:
    import psycopg  # lazy, as in ingest_games.py
    with psycopg.connect(dsn) as conn:
        cur = conn.execute(QUERY, [model])
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def render(c: CatalogueCheck) -> str:
    mark = {True: "PASS", False: "FAIL"}
    ch = c.checks
    lines = [
        "# Hosted catalogue check (TM11-159)", "",
        f"- **Checked:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- **Embedding model:** `{c.model}`",
        f"- **Result:** {'PASS' if c.ok else 'FAIL'}", "",
        "| Check | Result | Detail |", "|---|---|---|",
        f"| Size | {mark[ch['size']]} | {c.games} games (need {c.min_games}+) |",
        f"| Duplicates | {mark[ch['duplicates']]} | {len(c.duplicate_appids)} shared steam_appid, "
        f"{len(c.duplicate_titles)} shared title |",
        f"| Embedded | {mark[ch['embedded']]} | {c.embedded} of {c.games} have a vector |",
        f"| Benchmark titles | {mark[ch['benchmark']]} | "
        f"{c.benchmark_titles - len(c.missing_benchmark_titles)} of {c.benchmark_titles} present |",
        "", "Field coverage (reported, not failed: the AC says \"where available\"):", "",
        f"- missing description: {c.missing_description}",
        f"- missing genres: {c.missing_genres}",
        f"- missing steam_appid: {c.missing_steam_appid}",
    ]
    for label, items in (("Duplicate steam_appid", c.duplicate_appids),
                         ("Duplicate titles", c.duplicate_titles),
                         ("Not embedded", c.unembedded_titles),
                         ("Benchmark titles missing", c.missing_benchmark_titles)):
        if items:
            lines += ["", f"{label}:", ""] + [f"- {x}" for x in items[:50]]
            if len(items) > 50:
                lines.append(f"- … and {len(items) - 50} more (see the .json)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check the hosted catalogue after a rebuild.")
    ap.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    ap.add_argument("--model", default=os.environ.get("EMBEDDING_MODEL") or DEFAULT_MODEL)
    ap.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    a = ap.parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("verify_catalogue: DATABASE_URL is not set, so there is nothing to check.")
        return 2
    c = evaluate(fetch_rows(dsn, a.model), benchmark_titles(), a.model, a.min_games)
    md = render(c)
    a.report_dir.mkdir(parents=True, exist_ok=True)
    (a.report_dir / "tm11-159-catalogue-check.md").write_text(md)
    (a.report_dir / "tm11-159-catalogue-check.json").write_text(
        json.dumps(asdict(c) | {"checks": c.checks, "ok": c.ok}, indent=2) + "\n")
    print(md)
    return 0 if c.ok else 1


if __name__ == "__main__":
    sys.exit(main())
