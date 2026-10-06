#!/usr/bin/env python3
"""Ingestion data validation and run reporting (stdlib only).

Usage in the ingestion job:

    from ingestion_report import validate_rows, write_run_report
    result = validate_rows(rows)            # AC-01
    good_rows = result.valid_rows           # only these get upserted
    write_run_report(result, run_id=..., source="rawg")   # AC-02 + AC-03

CLI (validate a JSON array or JSONL of rows already fetched):

    python3 scripts/ingestion_report.py out/games.json --source rawg
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from purchase_links import PLATFORMS as LINK_PLATFORMS, check_link, link_coverage, normalise_url

# ---- Field config: edit these to match sql/03_tables.sql / field_mapping.md ----
# Row identity is the pair (source, source_id), e.g. ("rawg", 3498).
SOURCE_FIELD = "source"
SOURCE_ID_FIELD = "source_id"
TITLE_FIELD = "title"
DESCRIPTION_FIELD = "description"
GENRES_FIELD = "genres"
PLATFORMS_FIELD = "available_platforms"
SCORE_FIELDS = ("review_score", "critic_score")  # a row has a score if any is present
ARRAY_FIELDS = ("genres", "tags", "available_platforms")
KNOWN_PLATFORMS = {"STEAM", "XBOX", "EPIC", "PLAYSTATION", "GOG", "NINTENDO", "OTHER"}
ARTIFACT_ROOT = Path("artifacts/ingestion")
# --------------------------------------------------------------------------------


@dataclass
class RowResult:
    index: int
    key: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ValidationResult:
    rows: list[dict]
    results: list[RowResult]

    @property
    def valid_rows(self) -> list[dict]:
        return [r for r, res in zip(self.rows, self.results) if res.ok]

    @property
    def invalid(self) -> list[RowResult]:
        return [res for res in self.results if not res.ok]


def _blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) == 0
    return False


def _scores(row: dict) -> list[tuple[str, object]]:
    return [(f, row[f]) for f in SCORE_FIELDS if not _blank(row.get(f))]


def _has_id(row: dict) -> bool:
    return not _blank(row.get(SOURCE_FIELD)) and not _blank(row.get(SOURCE_ID_FIELD))


def _row_key(row: dict, i: int) -> str:
    if _has_id(row):
        return f"{row[SOURCE_FIELD]}:{row[SOURCE_ID_FIELD]}"
    return f"row#{i}"


def validate_row(row: dict, i: int) -> RowResult:
    res = RowResult(index=i, key=_row_key(row, i))
    if not _has_id(row):
        res.errors.append(f"missing {SOURCE_FIELD} or {SOURCE_ID_FIELD}")
    if _blank(row.get(TITLE_FIELD)):
        res.errors.append(f"missing {TITLE_FIELD}")
    elif not isinstance(row[TITLE_FIELD], str):
        res.errors.append(f"{TITLE_FIELD} is not a string")

    for f in ARRAY_FIELDS:
        v = row.get(f)
        if v is None:
            continue
        if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) for x in v):
            res.errors.append(f"{f} must be an array of strings")

    for f, s in _scores(row):
        if isinstance(s, bool) or not isinstance(s, (int, float)):
            res.errors.append(f"{f} is not numeric")
        elif not 0 <= s <= 100:
            res.errors.append(f"{f} {s} outside 0-100 (unscaled RAWG 0-5 value?)")
        elif 0 < s <= 5:
            res.warnings.append(f"{f} {s} looks like an unscaled 0-5 rating")

    pl = row.get("purchase_links")
    if pl is not None and not isinstance(pl, dict):
        res.errors.append("purchase_links must be an object")
    elif isinstance(pl, dict):
        # TM11-37: a bad link is dropped by the ingest job, not a reason to lose the game
        bad = sorted(str(k) for k, u in pl.items()
                     if check_link(k, normalise_url(u) if isinstance(u, str) else u))
        if bad:
            res.warnings.append(f"invalid purchase link: {', '.join(bad)}")

    desc = row.get(DESCRIPTION_FIELD)
    if isinstance(desc, str) and "\nEspañol" in desc:
        res.warnings.append("description contains appended non-English translation")

    plats = row.get(PLATFORMS_FIELD)
    if isinstance(plats, (list, tuple)):
        unknown = sorted({p for p in plats if isinstance(p, str) and p.upper() not in KNOWN_PLATFORMS})
        if unknown:
            res.warnings.append(f"unrecognised platform values: {', '.join(unknown)}")

    rd = row.get("release_date")
    if not _blank(rd) and not isinstance(rd, (date, datetime)):
        try:
            date.fromisoformat(str(rd)[:10])
        except ValueError:
            res.warnings.append(f"release_date not ISO-8601: {rd!r}")
    return res


def validate_rows(rows: list[dict]) -> ValidationResult:
    """AC-01: every row is checked; duplicates of an external id are rejected."""
    results = [validate_row(r, i) for i, r in enumerate(rows)]
    seen: dict[str, int] = {}
    for r, res in zip(rows, results):
        if _has_id(r):
            k = res.key
            if k in seen:
                res.errors.append(f"duplicate of row #{seen[k]} ({k})")
            else:
                seen[k] = res.index
    return ValidationResult(rows=rows, results=results)


def coverage(rows: list[dict]) -> dict[str, dict]:
    """AC-02: share of rows with a usable value for each reported field group."""
    n = len(rows)
    counts = {
        "description": sum(not _blank(r.get(DESCRIPTION_FIELD)) for r in rows),
        "genres": sum(not _blank(r.get(GENRES_FIELD)) for r in rows),
        "scores": sum(bool(_scores(r)) for r in rows),
        "platforms": sum(not _blank(r.get(PLATFORMS_FIELD)) for r in rows),
        "purchase_links": link_coverage(rows)["any"]["present"],
    }
    return {k: {"present": v, "total": n, "pct": round(100 * v / n, 1) if n else 0.0}
            for k, v in counts.items()}


def build_summary(result: ValidationResult, run_id: str, source: str) -> dict:
    reasons = Counter(e.split(" (")[0] for res in result.invalid for e in res.errors)
    warns = Counter(w.split(":")[0] for res in result.results for w in res.warnings)
    return {
        "run_id": run_id,
        "source": source,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows_total": len(result.rows),
        "rows_valid": len(result.valid_rows),
        "rows_rejected": len(result.invalid),
        "rejection_reasons": dict(reasons.most_common()),
        "warning_counts": dict(warns.most_common()),
        "coverage_valid_rows": coverage(result.valid_rows),
        "coverage_all_rows": coverage(result.rows),
        "purchase_link_coverage": link_coverage(result.valid_rows),
        "rejected": [{"index": r.index, "key": r.key, "errors": r.errors} for r in result.invalid],
    }


def render_markdown(s: dict) -> str:
    L = [f"# Ingestion run report — {s['run_id']}", "",
         f"- **Source:** {s['source']}",
         f"- **Generated:** {s['generated_at']}",
         f"- **Rows fetched:** {s['rows_total']}",
         f"- **Passed validation:** {s['rows_valid']}",
         f"- **Rejected:** {s['rows_rejected']}", "",
         "## Field coverage", "",
         "Percentages are of rows that passed validation (the corpus that is actually ingested).",
         "The all-rows column shows the same measure before rejects were removed.", "",
         "| Field | Present | Coverage (valid rows) | Coverage (all rows) |",
         "|---|---|---|---|"]
    for k in ("description", "genres", "scores", "platforms", "purchase_links"):
        v, a = s["coverage_valid_rows"][k], s["coverage_all_rows"][k]
        L.append(f"| {k} | {v['present']} / {v['total']} | {v['pct']}% | {a['pct']}% |")
    L += ["", "## Purchase link coverage", "",
          "Rows (passed validation) holding a validated storefront link. Absent means the",
          "source gave no usable URL; nothing is filled in or guessed.", "",
          "| Storefront | Present | Coverage |", "|---|---|---|"]
    for k in ("any", *LINK_PLATFORMS):
        v = s["purchase_link_coverage"][k]
        L.append(f"| {k} | {v['present']} / {v['total']} | {v['pct']}% |")
    L += ["", "## Rejections", ""]
    if s["rejection_reasons"]:
        L += ["| Reason | Rows |", "|---|---|"] + [f"| {k} | {v} |" for k, v in s["rejection_reasons"].items()]
        L += ["", "Rejected rows:", ""]
        L += [f"- `{r['key']}` (input index {r['index']}): {'; '.join(r['errors'])}" for r in s["rejected"][:50]]
        if len(s["rejected"]) > 50:
            L.append(f"- … and {len(s['rejected']) - 50} more (see JSON artifact)")
    else:
        L.append("None.")
    L += ["", "## Warnings (rows still ingested)", ""]
    if s["warning_counts"]:
        L += ["| Warning | Rows |", "|---|---|"] + [f"| {k} | {v} |" for k, v in s["warning_counts"].items()]
    else:
        L.append("None.")
    return "\n".join(L) + "\n"


def write_run_report(result: ValidationResult, run_id: str, source: str,
                     root: Path = ARTIFACT_ROOT) -> Path:
    """AC-03: persist the report as a job artifact (markdown + machine-readable JSON)."""
    s = build_summary(result, run_id, source)
    out = Path(root) / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "ingestion_report.json").write_text(json.dumps(s, indent=2))
    md = out / "ingestion_report.md"
    md.write_text(render_markdown(s))
    return md


def _load(path: str) -> list[dict]:
    text = Path(path).read_text()
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        return [json.loads(l) for l in text.splitlines() if l.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("--source", default="unknown")
    ap.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ap.add_argument("--out", default=str(ARTIFACT_ROOT))
    a = ap.parse_args(argv)
    result = validate_rows(_load(a.input))
    path = write_run_report(result, a.run_id, a.source, Path(a.out))
    print(f"{len(result.valid_rows)}/{len(result.rows)} valid; report: {path}")
    return 0 if result.rows else 1


if __name__ == "__main__":
    sys.exit(main())
