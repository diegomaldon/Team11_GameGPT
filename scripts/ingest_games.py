#!/usr/bin/env python3
"""Catalogue ingestion job: load a defined subset of titles into `games`.

  AC-01  loads a defined subset (default: top-N by popularity), target 3000+
  AC-02  idempotent by external id (ON CONFLICT (<id col>) DO UPDATE; identical rows are skipped)
  AC-03  rejected rows are written to rejects.jsonl and logged, never swallowed
  AC-04  duration and record counts are reported (stdout + artifact)
  TM11-37 purchase links are re-validated; bad links are dropped and counted, the game is kept

Row source is pluggable so the job does not care how rows were fetched:

  # rows already fetched by fetch_metadata.py (JSON array or JSONL)
  python3 scripts/ingest_games.py --source-json out/games.json --dry-run

  # call your TM11-33 client: module:function returning an iterable of rows,
  # called as function(limit=<int>)
  python3 scripts/ingest_games.py --source-func rawg_client:fetch_top_games --limit 3000

Database: set DATABASE_URL (use the service_role connection; `games` is
write-restricted by RLS). Without --dry-run, needs `pip install "psycopg[binary]"`.
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol

import purchase_links
from ingestion_report import ARTIFACT_ROOT, _load, validate_rows, write_run_report

log = logging.getLogger("ingest_games")

# source name in the row  ->  unique id column in `games`
ID_COLUMN = {"rawg": "rawg_id", "igdb": "igdb_id", "steam": "steam_appid"}
# columns written on every upsert (id column is added per row)
DATA_COLUMNS = ("title", "description", "genres", "tags", "available_platforms",
                "purchase_links", "critic_score", "review_score", "release_date",
                "developers", "publishers", "header_image_url")
DEFAULT_LIMIT = 3000
BATCH_SIZE = 200


class Store(Protocol):
    def upsert(self, row: dict) -> str:
        """Upsert one row. Return 'inserted' or 'updated'. Raise on failure."""


class InMemoryStore:
    """Dry-run / test store. Same idempotency contract as the Postgres one."""

    def __init__(self):
        self.rows: dict[tuple, dict] = {}

    def upsert(self, row: dict) -> str:
        key = (row["source"], str(row["source_id"]))
        new = {"source_id": str(row["source_id"]), **normalise(row)}
        if key not in self.rows:
            state = "inserted"
        elif self.rows[key] == new:
            state = "unchanged"
        else:
            state = "updated"
        self.rows[key] = new
        return state

    def commit(self): ...
    def close(self): ...


# Column types from sql/03_tables.sql. Explicit casts matter: psycopg sends Python
# lists of str as text[], and Postgres will not implicitly cast that to the
# platform_type[] enum array on INSERT.
PG_CAST = {
    "title": "text", "description": "text", "genres": "text[]", "tags": "text[]",
    "available_platforms": "public.platform_type[]", "purchase_links": "jsonb",
    "critic_score": "smallint", "review_score": "smallint", "release_date": "date",
    "developers": "text[]", "publishers": "text[]", "header_image_url": "text",
}
# NOT NULL DEFAULT columns: an explicit NULL does NOT fall back to the default,
# so a missing value must be sent as an empty array / object.
EMPTY_DEFAULT = {"genres": [], "tags": [], "available_platforms": [],
                 "developers": [], "publishers": [], "purchase_links": {}}


def normalise(row: dict) -> dict:
    out = {c: row.get(c) for c in DATA_COLUMNS}
    for c, empty in EMPTY_DEFAULT.items():
        if out[c] is None:
            out[c] = type(empty)()
    return out


def build_upsert_sql(id_col: str) -> str:
    cols = [id_col, *DATA_COLUMNS]
    values = ", ".join(["%s"] + [f"%s::{PG_CAST[c]}" for c in DATA_COLUMNS])
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in DATA_COLUMNS)
    old = ", ".join(f"games.{c}" for c in DATA_COLUMNS)
    new = ", ".join(f"EXCLUDED.{c}" for c in DATA_COLUMNS)
    # WHERE .. IS DISTINCT FROM: an identical re-run touches nothing (no row
    # returned), so updated_at is not churned and embeddings are not invalidated.
    return (f"INSERT INTO public.games ({', '.join(cols)}) VALUES ({values}) "
            f"ON CONFLICT ({id_col}) DO UPDATE SET {sets} "
            f"WHERE ({old}) IS DISTINCT FROM ({new}) "
            f"RETURNING (xmax = 0) AS inserted")


class PostgresStore:
    """Upserts into `games` keyed on the per-source unique id column.

    Never writes `embedding`, so existing embeddings survive a re-ingest.
    """

    def __init__(self, dsn: str):
        import psycopg  # lazy: not needed for dry runs / tests
        from psycopg.types.json import Jsonb
        self._Jsonb = Jsonb
        self.conn = psycopg.connect(dsn)

    def upsert(self, row: dict) -> str:
        data = normalise(row)
        vals = [int(row["source_id"])]
        for c in DATA_COLUMNS:
            v = data[c]
            vals.append(self._Jsonb(v) if c == "purchase_links" else v)
        sql = build_upsert_sql(ID_COLUMN[row["source"]])
        # nested transaction = savepoint, so one bad row can't poison the batch
        with self.conn.transaction():
            res = self.conn.execute(sql, vals).fetchone()
        if res is None:
            return "unchanged"
        return "inserted" if res[0] else "updated"

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


@dataclass
class RunStats:
    run_id: str
    source: str
    started_at: str = ""
    limit: int = 0
    target: int = 0
    fetched: int = 0
    valid: int = 0
    rejected_validation: int = 0
    rejected_database: int = 0
    links_kept: int = 0
    links_dropped: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    fetch_seconds: float = 0.0
    load_seconds: float = 0.0
    total_seconds: float = 0.0
    target_met: bool = False
    dry_run: bool = False
    reject_file: str = ""
    notes: list[str] = field(default_factory=list)
    dropped_links: list[dict] = field(default_factory=list)

    @property
    def rejected(self) -> int:
        return self.rejected_validation + self.rejected_database

    @property
    def loaded(self) -> int:
        return self.inserted + self.updated + self.unchanged


def _write_rejects(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for e in entries:
            fh.write(json.dumps(e, default=str) + "\n")


def _clean_links(row: dict, stats: RunStats) -> dict:
    """Drop purchase links that fail validation. Never adds a link."""
    pl = row.get("purchase_links")
    if not isinstance(pl, dict) or not pl:
        return row  # absent stays absent; a non-object is rejected by validation
    res = purchase_links.clean(pl)
    stats.links_kept += len(res.links)
    stats.links_dropped += len(res.rejected)
    key = f"{row.get('source')}:{row.get('source_id')}"
    for platform, url, reason in res.rejected:
        log.warning("dropped %s purchase link for %s: %s", platform, key, reason)
        stats.dropped_links.append({"key": key, "platform": platform, "url": url, "reason": reason})
    return {**row, "purchase_links": res.links}


def run_job(rows: Iterable[dict], store: Store, run_id: str, source: str,
            limit: int = DEFAULT_LIMIT, target: int = DEFAULT_LIMIT,
            artifact_root: Path = ARTIFACT_ROOT, dry_run: bool = False) -> RunStats:
    t0 = time.perf_counter()
    stats = RunStats(run_id=run_id, source=source, limit=limit, target=target, dry_run=dry_run,
                     started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out = Path(artifact_root) / run_id

    # --- fetch (the defined subset) ---
    fetched: list[dict] = []
    for r in rows:
        fetched.append(_clean_links(r, stats))
        if len(fetched) >= limit:
            break
    stats.fetched = len(fetched)
    stats.fetch_seconds = round(time.perf_counter() - t0, 3)

    # --- validate (TM11-35) ---
    result = validate_rows(fetched)
    rejects: list[dict] = []
    for res in result.invalid:
        stats.rejected_validation += 1
        log.warning("rejected %s (validation): %s", res.key, "; ".join(res.errors))
        rejects.append({"stage": "validation", "index": res.index, "key": res.key,
                        "errors": res.errors, "row": fetched[res.index]})
    unknown = [r for r in result.valid_rows if r["source"] not in ID_COLUMN]
    good = [r for r in result.valid_rows if r["source"] in ID_COLUMN]
    for r in unknown:
        stats.rejected_validation += 1
        msg = f"unsupported source {r['source']!r} (no id column mapping)"
        log.warning("rejected %s:%s (validation): %s", r["source"], r["source_id"], msg)
        rejects.append({"stage": "validation", "key": f"{r['source']}:{r['source_id']}",
                        "errors": [msg], "row": r})
    stats.valid = len(good)

    # --- load (idempotent upsert; commit per batch) ---
    t1 = time.perf_counter()
    for i, row in enumerate(good, 1):
        try:
            state = store.upsert(row)
            stats.inserted += state == "inserted"
            stats.updated += state == "updated"
            stats.unchanged += state == "unchanged"
        except Exception as exc:  # noqa: BLE001 - logged and recorded, not swallowed
            stats.rejected_database += 1
            key = f"{row['source']}:{row['source_id']}"
            log.error("rejected %s (database): %s", key, exc)
            rejects.append({"stage": "database", "key": key, "errors": [str(exc)], "row": row})
        if i % BATCH_SIZE == 0:
            store.commit()
    store.commit()
    stats.load_seconds = round(time.perf_counter() - t1, 3)

    stats.target_met = stats.loaded >= target
    if not stats.target_met:
        stats.notes.append(f"target shortfall: loaded {stats.loaded} < target {target}")
    if rejects:
        rp = out / "rejects.jsonl"
        _write_rejects(rp, rejects)
        stats.reject_file = str(rp)
    stats.total_seconds = round(time.perf_counter() - t0, 3)

    # --- report (AC-04) + coverage artifact (TM11-35) ---
    write_run_report(result, run_id, source, Path(artifact_root))
    _write_run_summary(stats, out)
    return stats


def _write_run_summary(s: RunStats, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "ingestion_run.json").write_text(json.dumps(asdict(s) | {
        "rejected": s.rejected, "loaded": s.loaded}, indent=2))
    rate = round(s.loaded / s.load_seconds, 1) if s.load_seconds else 0
    md = [f"# Ingestion job — {s.run_id}", "",
          f"- **Source:** {s.source}{'  (dry run, nothing written to the database)' if s.dry_run else ''}",
          f"- **Started:** {s.started_at}",
          f"- **Duration:** {s.total_seconds}s total ({s.fetch_seconds}s fetch, {s.load_seconds}s load, {rate} rows/s)",
          "", "| Metric | Count |", "|---|---|",
          f"| Fetched (limit {s.limit}) | {s.fetched} |",
          f"| Passed validation | {s.valid} |",
          f"| Inserted (new) | {s.inserted} |",
          f"| Updated (present, values changed) | {s.updated} |",
          f"| Unchanged (present, identical) | {s.unchanged} |",
          f"| Rejected — validation | {s.rejected_validation} |",
          f"| Rejected — database | {s.rejected_database} |",
          f"| Purchase links kept | {s.links_kept} |",
          f"| Purchase links dropped (failed validation) | {s.links_dropped} |",
          f"| **Loaded total** | **{s.loaded}** |", "",
          f"**Target {s.target}+:** {'MET' if s.target_met else 'NOT MET'}", ""]
    if s.reject_file:
        md.append(f"Rejected rows and reasons: `{s.reject_file}`")
    md += [f"- {n}" for n in s.notes]
    if s.dropped_links:
        md += ["", "Dropped purchase links:", ""]
        md += [f"- `{d['key']}` {d['platform']}: {d['reason']}" for d in s.dropped_links[:50]]
        if len(s.dropped_links) > 50:
            md.append(f"- … and {len(s.dropped_links) - 50} more (see ingestion_run.json)")
    md += ["", "Field coverage: see `ingestion_report.md` in this folder."]
    (out / "ingestion_run.md").write_text("\n".join(md) + "\n")


def _source_from_func(spec: str, limit: int) -> Iterable[dict]:
    mod, _, fn = spec.partition(":")
    sys.path.insert(0, os.getcwd())
    return getattr(importlib.import_module(mod), fn)(limit=limit)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--source-json", help="JSON/JSONL file of rows in the prototype schema")
    src.add_argument("--source-func", help="module:function returning an iterable of rows")
    ap.add_argument("--source", default="rawg", help="label for the report (default rawg)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--target", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("ingest-%Y%m%dT%H%M%SZ"))
    ap.add_argument("--out", default=str(ARTIFACT_ROOT))
    ap.add_argument("--dry-run", action="store_true", help="validate and report; do not touch the database")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    rows = _load(a.source_json) if a.source_json else _source_from_func(a.source_func, a.limit)
    if a.dry_run:
        store: Store = InMemoryStore()
    else:
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            ap.error("DATABASE_URL is not set (or use --dry-run)")
        store = PostgresStore(dsn)
    try:
        s = run_job(rows, store, a.run_id, a.source, a.limit, a.target, Path(a.out), a.dry_run)
    finally:
        store.close()
    print(f"[{s.run_id}] fetched={s.fetched} valid={s.valid} inserted={s.inserted} updated={s.updated} unchanged={s.unchanged} "
          f"rejected={s.rejected} duration={s.total_seconds}s target={'met' if s.target_met else 'NOT MET'}")
    print(f"report: {Path(a.out) / s.run_id / 'ingestion_run.md'}")
    return 0 if s.target_met else 2


if __name__ == "__main__":
    sys.exit(main())
