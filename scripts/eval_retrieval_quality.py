"""Evaluate retrieval quality against the TM11-63 benchmark (TM11-67).

For each of the 20 benchmark prompts this records precision at 5 for two
pipelines and compares them:

  before  top results by cosine similarity alone (the pipeline before TM11-65)
  after   HybridRetriever's merge at the tuned weights (semantic 0.7, metadata
          0.3, pool 50), the pipeline the recommend endpoint runs today

It also sweeps the metadata weight from 0.0 to 0.5 at the tuned pool, so the
effect of the weighting can be told apart from the effect of removing named and
ruled-out games (weight 0.0 does only the removal). The searches are the same
ones scripts/eval_hybrid_retrieval.py runs (its `gather` is reused), so the two
artifacts measure the same thing at different cut-offs.

Scoring and the comparison are api/services/retrieval_quality.py. This file
fetches the results and writes the report; the model, database and retrieval
imports are deferred so the report code can be tested offline.

Usage (repo root, venv active, DATABASE_URL pointing at a catalogue with
embeddings; the stub embedding is refused). Only reads from the database:
    python scripts/eval_retrieval_quality.py
    python scripts/eval_retrieval_quality.py --out artifacts/sprint9
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.services.query_benchmark import BenchmarkQuery, load_query_benchmark  # noqa: E402
from api.services.retrieval_quality import (  # noqa: E402
    PRECISION_K,
    PromptScore,
    Summary,
    by_category,
    compare,
    outcome_counts,
    score_prompt,
    summarise,
    weakest_categories,
)

SWEEP_WEIGHTS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
ARTIFACT_NAME = "tm11-67-retrieval-quality"


# ─────────────────────────── report (pure, testable) ───────────────────────────


def _summary(s: Summary) -> dict:
    return {"prompts": s.prompts, "mean_p@5": s.mean_precision,
            "mean_normalised": s.mean_normalised, "mrr": s.mrr,
            "zero_hit_prompts": s.zero_hit_prompts}


def _scores(benchmark: Sequence[BenchmarkQuery], titles: Sequence[Sequence[str]]) -> list[PromptScore]:
    if len(benchmark) != len(titles):
        raise ValueError("one result list per benchmark prompt")
    return [score_prompt(q, list(t), PRECISION_K) for q, t in zip(benchmark, titles)]


def build_report(
    benchmark: Sequence[BenchmarkQuery],
    before_titles: Sequence[Sequence[str]],
    after_titles: Sequence[Sequence[str]],
    sweep_titles: dict[float, Sequence[Sequence[str]]],
    catalogue_titles: set[str],
    meta: dict,
) -> dict:
    """Everything the artifact records, from the ranked titles of each run."""
    before = _scores(benchmark, before_titles)
    after = _scores(benchmark, after_titles)
    changes = compare(before, after)
    before_cat, after_cat = by_category(before), by_category(after)

    sweep = {}
    for weight, titles in sorted(sweep_titles.items()):
        scores = _scores(benchmark, titles)
        sweep[str(weight)] = {
            "all": _summary(summarise("all", scores)),
            **{c: _summary(s) for c, s in by_category(scores).items()},
        }

    return {
        **meta,
        "k": PRECISION_K,
        "benchmark_queries": len(benchmark),
        "before": _summary(summarise("all", before)),
        "after": _summary(summarise("all", after)),
        "outcomes": outcome_counts(changes),
        "by_category": {
            c: {"before": _summary(before_cat[c]), "after": _summary(after_cat[c])}
            for c in after_cat
        },
        "weakest_categories": [s.name for s in weakest_categories(after)],
        "sweep": sweep,
        "per_query": [
            {
                "id": ch.id, "category": ch.category, "prompt": ch.after.prompt,
                "attainable": ch.after.attainable,
                "before_p@5": ch.before.precision, "after_p@5": ch.after.precision,
                "delta": ch.delta, "outcome": ch.outcome,
                "before_first_hit": ch.before.first_hit_rank,
                "after_first_hit": ch.after.first_hit_rank,
                "before_top_5": list(ch.before.top_k), "after_top_5": list(ch.after.top_k),
                "expected_titles": list(q.expected_titles),
                "expected_missing_from_catalogue": sorted(
                    set(q.expected_titles) - catalogue_titles),
            }
            for ch, q in zip(changes, benchmark)
        ],
    }


def _signed(x: float) -> str:
    return f"{x:+.3f}" if x else "0"


def to_markdown(r: dict) -> str:
    def row(label: str, s: dict) -> str:
        return (f"| {label} | {s['mean_p@5']} | {s['mean_normalised']} | {s['mrr']} | "
                f"{s['zero_hit_prompts']}/{s['prompts']} |")

    o = r["outcomes"]
    lines = [
        "# TM11-67 retrieval quality: precision at 5 on the benchmark",
        "",
        f"Run {r['run_at']} on the `{r['schema']}` schema ({r['catalogue_games']} games) with "
        f"`{r['model']}`, against the {r['benchmark_queries']} TM11-63 benchmark prompts. "
        "Written by `scripts/eval_retrieval_quality.py`; read-only against the database.",
        "",
        "**Before:** top results by similarity alone (the pipeline before TM11-65). "
        f"**After:** hybrid retrieval at semantic {1 - r['metadata_weight']:.1f} / metadata "
        f"{r['metadata_weight']}, pool {r['pool_size']} (the current pipeline).",
        "",
        f"P@5 is expected titles in the top 5 divided by 5. Most prompts list four expected "
        "titles, so a perfect answer scores 0.8; *normalised* divides by what each prompt "
        "allows. A title the prompt names (\"like X\") never counts.",
        "",
        "| | mean P@5 | mean normalised | MRR | prompts with no hit in top 5 |",
        "|---|---|---|---|---|",
        row("Before", r["before"]),
        row("After", r["after"]),
        "",
        f"Per prompt: **{o['improved']} improved, {o['regressed']} regressed, "
        f"{o['unchanged']} unchanged.**",
        "",
        "## By category",
        "",
        "Weakest first (after, by mean normalised P@5, then MRR).",
        "",
        "| Category | Before P@5 | After P@5 | Change | Before normalised | After normalised | "
        "After no-hit prompts |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in r["weakest_categories"]:
        b, a = r["by_category"][c]["before"], r["by_category"][c]["after"]
        lines.append(
            f"| {c} | {b['mean_p@5']} | {a['mean_p@5']} | "
            f"{_signed(round(a['mean_p@5'] - b['mean_p@5'], 3))} | {b['mean_normalised']} | "
            f"{a['mean_normalised']} | {a['zero_hit_prompts']}/{a['prompts']} |")

    categories = list(r["by_category"])
    lines += [
        "",
        "## Metadata weight sweep",
        "",
        f"Mean P@5 at pool {r['pool_size']}. Weight 0.0 is similarity order with named and "
        "ruled-out games removed, so the step from *Before* to 0.0 is the removal alone and "
        "the steps after it are the weighting.",
        "",
        "| Metadata weight | all | " + " | ".join(categories) + " |",
        "|---|---|" + "---|" * len(categories),
        "| Before | " + " | ".join(
            [str(r["before"]["mean_p@5"])]
            + [str(r["by_category"][c]["before"]["mean_p@5"]) for c in categories]) + " |",
    ]
    for weight, s in r["sweep"].items():
        chosen = " (chosen)" if float(weight) == r["metadata_weight"] else ""
        lines.append(f"| {weight}{chosen} | " + " | ".join(
            [str(s["all"]["mean_p@5"])] + [str(s[c]["mean_p@5"]) for c in categories]) + " |")

    lines += [
        "",
        "## Per prompt",
        "",
        "| Id | Best possible | Before P@5 | After P@5 | Change | After first hit | "
        "After top 5 |",
        "|---|---|---|---|---|---|---|",
    ]
    for q in r["per_query"]:
        lines.append(
            f"| {q['id']} | {q['attainable']} | {q['before_p@5']} | {q['after_p@5']} | "
            f"{_signed(q['delta'])} | {q['after_first_hit'] or '-'} | "
            f"{', '.join(q['after_top_5'])} |")

    missing = [q for q in r["per_query"] if q["expected_missing_from_catalogue"]]
    lines += ["", "## Catalogue coverage", ""]
    if missing:
        lines += ["Expected titles that aren't in this catalogue can never be retrieved, so "
                  "they cap the prompt's score below *best possible*.", "",
                  "| Id | Missing expected titles |", "|---|---|"]
        lines += [f"| {q['id']} | {', '.join(q['expected_missing_from_catalogue'])} |"
                  for q in missing]
    else:
        lines.append("Every expected title is in this catalogue.")
    return "\n".join(lines) + "\n"


# ─────────────────────────── live run ───────────────────────────


async def collect() -> dict:
    """Run the searches and return everything build_report needs."""
    from api.db import repositories
    from api.db.schema import catalogue_shape
    from api.services.embedding import STUB_MODEL_NAME, EmbeddingService
    from api.services.hybrid_retrieval import (
        DEFAULT_METADATA_WEIGHT,
        DEFAULT_POOL_SIZE,
        RetrievalWeights,
        merge_and_score,
    )
    from api.services.query_parser import TitleIndex
    from api.services.title_matching import catalogue_from_rows
    from api.services.vector_store import VectorStore
    from eval_hybrid_retrieval import gather

    embedder = EmbeddingService()
    if embedder.model_name == STUB_MODEL_NAME:
        raise SystemExit("eval_retrieval_quality: the stub embedding can't be evaluated")
    store = VectorStore(model=embedder.model_name)
    rows = await repositories.list_catalogue_titles()
    index = TitleIndex(catalogue_from_rows(rows))
    benchmark = load_query_benchmark()
    gathered = await gather(benchmark, embedder, store, index)

    def merged(weight: float) -> list[list[str]]:
        weights = RetrievalWeights(semantic=1 - weight, metadata=weight)
        out = []
        for g in gathered:
            legs = [g["semantic"][:DEFAULT_POOL_SIZE]]
            if g["filtered"] is not None:
                legs.append(g["filtered"][:DEFAULT_POOL_SIZE])
            out.append([s.candidate.title for s in merge_and_score(legs, g["parsed"], weights)])
        return out

    return {
        "benchmark": benchmark,
        "before_titles": [[c.title for c in g["semantic"]] for g in gathered],
        "after_titles": merged(DEFAULT_METADATA_WEIGHT),
        "sweep_titles": {w: merged(w) for w in SWEEP_WEIGHTS},
        "catalogue_titles": {r["title"] for r in rows if r["title"]},
        "meta": {
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": await catalogue_shape(),
            "model": embedder.model_name,
            "catalogue_games": len(rows),
            "pool_size": DEFAULT_POOL_SIZE,
            "metadata_weight": DEFAULT_METADATA_WEIGHT,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("artifacts/sprint9"))
    args = parser.parse_args()
    from api.db import has_db
    if not has_db():
        print("eval_retrieval_quality: DATABASE_URL is not set")
        return 2
    report = build_report(**asyncio.run(collect()))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{ARTIFACT_NAME}.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    (args.out / f"{ARTIFACT_NAME}.md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
