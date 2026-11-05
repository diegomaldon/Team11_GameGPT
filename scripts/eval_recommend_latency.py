"""Time each recommend stage over the benchmark prompts. TM11-68 · REQ040.

Runs the 20 TM11-63 prompts through the real RAGPipeline (parse, embed, retrieve,
filter, rank) and reports each stage's p50 and p95 against its budget, the same way
the weekly check reads the Render logs. The pipeline is called directly rather than
through POST /api/recommend, so nothing is saved to the query history.

Without GEMINI_API_KEY or ANTHROPIC_API_KEY the rank stage times the offline
fallback, not a model, and the report says so. Real rank numbers come from the
weekly check on Render (scripts/latency_report.py).

Writes artifacts/sprint9/tm11-68-recommend-latency.json and .md.

Usage (from the repo root, venv active, catalogue embedded):
    python scripts/eval_recommend_latency.py
    python scripts/eval_recommend_latency.py --repeats 5

Exits 2 without a database or with EMBEDDING_STUB=1, 1 when a stage is over budget.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import get_settings  # noqa: E402
from api.db import has_db  # noqa: E402
from api.db.schema import catalogue_shape  # noqa: E402
from api.observability.latency_report import LatencyReport, summarise, to_markdown  # noqa: E402
from api.observability.stage_timings import StageTimings  # noqa: E402
from api.services import (  # noqa: E402
    DeduplicationService,
    EmbeddingService,
    LLMService,
    RAGPipeline,
    VectorStore,
)
from api.services.query_benchmark import load_query_benchmark  # noqa: E402

ARTIFACT_DIR = Path("artifacts/sprint9")


async def time_benchmark(repeats: int) -> tuple[list[dict], bool, str]:
    """Stage timings for every prompt, `repeats` times each, after one warm-up run.

    Also returns whether rank ran offline, and the catalogue schema it ran against.
    """
    llm = LLMService()
    pipeline = RAGPipeline(EmbeddingService(), VectorStore(), DeduplicationService(), llm)
    user_id = UUID(get_settings().dev_user_id)
    prompts = [query.prompt for query in load_query_benchmark()]

    await pipeline.recommend(user_id, prompts[0])  # loads the model and the title list

    entries = []
    for prompt in prompts:
        for _ in range(repeats):
            timings = StageTimings()
            await pipeline.recommend(user_id, prompt, timings=timings)
            entries.append(timings.log_fields())
    return entries, llm.offline, await catalogue_shape()


def describe_run(report: LatencyReport, *, schema: str, repeats: int, is_offline: bool) -> str:
    ranker = "the offline fallback (no LLM key), so its numbers are not a model's" if is_offline \
        else "the configured LLM"
    intro = (
        f"Run {datetime.now(timezone.utc).isoformat(timespec='seconds')} on the local "
        f"`{schema}` schema: 20 benchmark prompts x {repeats} runs each, after one warm-up "
        f"run. Rank used {ranker}. Produced by `scripts/eval_recommend_latency.py`."
    )
    table = to_markdown(report, title="TM11-68 recommend latency by stage")
    heading, _, rest = table.partition("\n")
    return f"{heading}\n\n{intro}\n{rest}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    if not has_db():
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if os.environ.get("EMBEDDING_STUB") == "1":
        print("EMBEDDING_STUB=1 would time a hash, not the model", file=sys.stderr)
        return 2

    entries, is_offline, schema = asyncio.run(time_benchmark(args.repeats))
    report = summarise(entries)
    markdown = describe_run(report, schema=schema, repeats=args.repeats, is_offline=is_offline)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "tm11-68-recommend-latency.json").write_text(json.dumps({
        "schema": schema,
        "repeats_per_query": args.repeats,
        "rank_is_offline_fallback": is_offline,
        "runs": report.runs,
        "failures": report.failures,
        "stages": [asdict(s) for s in report.stages],
    }, indent=2) + "\n")
    (ARTIFACT_DIR / "tm11-68-recommend-latency.md").write_text(markdown)
    print(markdown)
    return 0 if report.is_within_budget else 1


if __name__ == "__main__":
    sys.exit(main())
