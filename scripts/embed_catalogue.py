"""Embed the games catalogue into public.game_embeddings (TM11-39, REQ011).

Runs EmbeddingPipeline (api/services/embedding_pipeline.py) against the
database in DATABASE_URL, prints a summary, and writes the run report to
artifacts/embeddings/<run id>/embedding_report.json.

Usage (from the repo root, with the venv active):
    python scripts/embed_catalogue.py                 # games with no vector yet
    python scripts/embed_catalogue.py --all           # re-embed every game
    python scripts/embed_catalogue.py --batch-size 64

Safe to stop and rerun: finished batches are kept, and the next run picks up
the rest. Exits 0 when every game has a vector, 1 when some are still missing
or the model can't load, and 2 when there is no database to write to.

Not the same as embed_games.py, which fills the old games.embedding column for
the local 0001_init.sql slice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import has_db  # noqa: E402
from api.services.embedding import EmbeddingModelError, EmbeddingService  # noqa: E402
from api.services.embedding_pipeline import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    EmbeddingPipeline,
    EmbeddingRunReport,
    format_cost_usd,
)

REPORT_ROOT = Path("artifacts/embeddings")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if not has_db():
        print("embed_catalogue: DATABASE_URL is not set, so there is nothing to embed into.")
        return 2

    embedder = EmbeddingService()
    if embedder.offline:
        print(f"embed_catalogue: EMBEDDING_STUB=1, saving stub vectors as {embedder.model_name}.")
    pipeline = EmbeddingPipeline(embedder, batch_size=args.batch_size)
    try:
        report = asyncio.run(pipeline.run(re_embed_all=args.re_embed_all))
    except EmbeddingModelError:
        logging.exception("embed_catalogue: stopped")
        print(f"embed_catalogue: could not load {embedder.model_name}. Is "
              "sentence-transformers installed (pip install -r api/requirements.txt)?")
        return 1

    report_path = _write_report(report, args.report_dir)
    print(_summary(report))
    print(f"embed_catalogue: report written to {report_path}")
    return 0 if report.is_complete else 1


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Embed the games catalogue in batches.")
    parser.add_argument(
        "--all", dest="re_embed_all", action="store_true",
        help="re-embed every game, not only games with no vector yet",
    )
    parser.add_argument("--batch-size", type=_positive_int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--report-dir", type=Path, default=REPORT_ROOT)
    return parser.parse_args(argv)


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _write_report(report: EmbeddingRunReport, report_dir: Path) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / run_id / "embedding_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_id": run_id, **report.to_dict()}, indent=2) + "\n")
    return path


def _summary(report: EmbeddingRunReport) -> str:
    status = "complete" if report.is_complete else "INCOMPLETE, rerun to finish"
    return (
        f"embed_catalogue: {status}. {report.embedded_count} embedded this run, "
        f"{len(report.failed_game_ids)} failed. {report.embedded_total} of "
        f"{report.catalogue_count} games have a {report.model} vector. "
        f"{report.token_count} tokens, cost {format_cost_usd(report.estimated_cost_usd)}, "
        f"{report.duration_seconds}s."
    )


if __name__ == "__main__":
    raise SystemExit(main())
