"""Tune and record hybrid retrieval against the TM11-63 benchmark (TM11-65).

For each of the 20 benchmark prompts: parse it with QueryParser (the real
catalogue's titles), embed it with the real model, run the plain semantic
search and the parsed-signal filtered search once each at the largest pool,
then score every (pool size, metadata weight) pair from those results. Exact
search (every IVFFlat list probed, or the hosted HNSW list widened to k) means
a smaller pool is the head of a larger one, so slicing gives the same answer as
asking again.

Reported per setting: hit@3 (what the LLM ranks from at n=3 is the top k, but
the first three are the strongest signal), hit@10, hit@20 (k=20 is what the
pipeline hands on), mean reciprocal rank, and expected titles found in the top
20. The baseline is the pipeline before TM11-65: top 20 by similarity, nothing
removed. The run is repeated to check the output is identical (deterministic).

Usage (repo root, venv active, DATABASE_URL pointing at a catalogue with
embeddings; the stub embedding is refused):
    python scripts/eval_hybrid_retrieval.py
    python scripts/eval_hybrid_retrieval.py --out artifacts/sprint9
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import has_db, repositories  # noqa: E402
from api.db.schema import catalogue_shape  # noqa: E402
from api.services.embedding import STUB_MODEL_NAME, EmbeddingService  # noqa: E402
from api.services.hybrid_retrieval import (  # noqa: E402
    DEFAULT_METADATA_WEIGHT,
    DEFAULT_POOL_SIZE,
    HybridRetriever,
    RetrievalWeights,
    merge_and_score,
    metadata_filters,
)
from api.services.query_benchmark import load_query_benchmark  # noqa: E402
from api.services.query_parser import TitleIndex, parse_query  # noqa: E402
from api.services.title_matching import catalogue_from_rows  # noqa: E402
from api.services.vector_store import VectorStore  # noqa: E402

POOL_SIZES = (10, 20, 30, 50, 100)
METADATA_WEIGHTS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5)
K = 20  # candidates the pipeline hands to dedup and the LLM


def _metrics(rows: list[dict]) -> dict:
    ranks = [r["rank"] for r in rows]
    return {
        "hit@3": sum(1 for x in ranks if x and x <= 3),
        "hit@10": sum(1 for x in ranks if x and x <= 10),
        "hit@20": sum(1 for x in ranks if x and x <= 20),
        "mrr": round(statistics.mean(1 / x if x else 0 for x in ranks), 3),
        "expected_found": sum(r["found"] for r in rows),
        "expected_total": sum(r["expected"] for r in rows),
    }


def _row(query, titles: list[str]) -> dict:
    top = titles[:K]
    return {
        "id": query.id,
        "category": query.category,
        "rank": query.hit_rank(top),
        "found": len(set(top) & set(query.expected_titles)),
        "expected": len(query.expected_titles),
        "top_5": top[:5],
    }


async def gather(benchmark, embedder, store, index) -> list[dict]:
    """Per prompt: its parse and both searches at the largest pool."""
    largest = max(POOL_SIZES)
    out = []
    for query in benchmark:
        parsed = parse_query(query.prompt, index)
        embedded = (await embedder.embed_documents([query.prompt]))[0]
        semantic = await store.top_k(embedded.vector, k=largest)
        filters = metadata_filters(parsed)
        filtered = None
        if filters is not None:
            filtered = await store.top_k(embedded.vector, k=largest, filters=filters)
        out.append({"query": query, "parsed": parsed, "semantic": semantic, "filtered": filtered})
    return out


def score(gathered: list[dict], pool: int, weight: float) -> list[dict]:
    weights = RetrievalWeights(semantic=1 - weight, metadata=weight)
    rows = []
    for g in gathered:
        legs = [g["semantic"][:pool]]
        if g["filtered"] is not None:
            legs.append(g["filtered"][:pool])
        ranked = merge_and_score(legs, g["parsed"], weights)
        rows.append(_row(g["query"], [s.candidate.title for s in ranked]))
    return rows


def ranked_titles(gathered: list[dict], pool: int, weight: float) -> list[list[str]]:
    """Every prompt's full merged list, for the determinism check."""
    weights = RetrievalWeights(semantic=1 - weight, metadata=weight)
    out = []
    for g in gathered:
        legs = [g["semantic"][:pool]]
        if g["filtered"] is not None:
            legs.append(g["filtered"][:pool])
        out.append([s.candidate.title for s in merge_and_score(legs, g["parsed"], weights)])
    return out


async def timing(gathered: list[dict], embedder, store, repeats: int = 5) -> dict:
    """Retrieval time per query, embedding excluded: before (one top-k) vs hybrid."""
    retriever = HybridRetriever(store)
    before, hybrid = [], []
    for g in gathered:
        vector = (await embedder.embed_documents([g["query"].prompt]))[0].vector
        for _ in range(repeats):
            started = time.perf_counter()
            await store.top_k(vector, k=K)
            before.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            await retriever.retrieve(vector, g["parsed"], k=K)
            hybrid.append((time.perf_counter() - started) * 1000)

    def summary(values: list[float]) -> dict:
        ordered = sorted(values)
        return {"p50": round(statistics.median(ordered), 2),
                "p95": round(ordered[int(0.95 * (len(ordered) - 1))], 2), "runs": len(ordered)}

    return {"before_ms": summary(before), "hybrid_ms": summary(hybrid)}


def baseline(gathered: list[dict]) -> list[dict]:
    """Before TM11-65: top K by similarity, nothing filtered, merged or removed."""
    return [_row(g["query"], [c.title for c in g["semantic"][:K]]) for g in gathered]


async def evaluate() -> dict:
    embedder = EmbeddingService()
    if embedder.model_name == STUB_MODEL_NAME:
        raise SystemExit("eval_hybrid_retrieval: the stub embedding can't be tuned against")
    store = VectorStore(model=embedder.model_name)
    index = TitleIndex(catalogue_from_rows(await repositories.list_catalogue_titles()))
    benchmark = load_query_benchmark()

    gathered = await gather(benchmark, embedder, store, index)
    grid = {
        f"{pool}|{weight}": _metrics(score(gathered, pool, weight))
        for pool in POOL_SIZES for weight in METADATA_WEIGHTS
    }
    chosen = score(gathered, DEFAULT_POOL_SIZE, DEFAULT_METADATA_WEIGHT)

    # Determinism: a second, independent pass (re-embedded, re-searched) must
    # produce the identical full list for every prompt.
    regathered = await gather(benchmark, embedder, store, index)
    is_deterministic = (
        ranked_titles(gathered, DEFAULT_POOL_SIZE, DEFAULT_METADATA_WEIGHT)
        == ranked_titles(regathered, DEFAULT_POOL_SIZE, DEFAULT_METADATA_WEIGHT)
    )
    latency = await timing(gathered, embedder, store)

    by_category = {}
    for name, rows in (("baseline", baseline(gathered)), ("hybrid", chosen)):
        for cat in sorted({r["category"] for r in rows}):
            in_category = [r for r in rows if r["category"] == cat]
            by_category.setdefault(cat, {})[name] = _metrics(in_category)

    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": await catalogue_shape(),
        "model": embedder.model_name,
        "catalogue_games": len(index),
        "benchmark_queries": len(benchmark),
        "k": K,
        "chosen": {"pool_size": DEFAULT_POOL_SIZE, "metadata_weight": DEFAULT_METADATA_WEIGHT},
        "deterministic": is_deterministic,
        "latency": latency,
        "baseline": _metrics(baseline(gathered)),
        "hybrid": _metrics(chosen),
        "grid": grid,
        "by_category": by_category,
        "per_query": [
            {**h, "baseline_rank": b["rank"], "baseline_top_5": b["top_5"],
             "parsed": {
                 "genres": list(g["parsed"].genres), "moods": list(g["parsed"].moods),
                 "platforms": list(g["parsed"].platforms),
                 "reference_titles": [r.title for r in g["parsed"].reference_titles],
             },
             "named_but_not_recognised": sorted(
                 set(g["query"].reference_titles)
                 - {r.title for r in g["parsed"].reference_titles}),
             "prompt": g["query"].prompt}
            for h, b, g in zip(chosen, baseline(gathered), gathered)
        ],
    }


DETERMINISTIC_YES = "yes, two independent runs gave identical full lists for every prompt"


def to_markdown(r: dict) -> str:
    before, hybrid = r["latency"]["before_ms"], r["latency"]["hybrid_ms"]
    def cells(m: dict) -> str:
        return (f"{m['hit@3']}/20 | {m['hit@10']}/20 | {m['hit@20']}/20 | {m['mrr']} | "
                f"{m['expected_found']}/{m['expected_total']}")

    lines = [
        "# TM11-65 hybrid retrieval: tuning and results",
        "",
        f"Run {r['run_at']} on the `{r['schema']}` schema ({r['catalogue_games']} games) with "
        f"`{r['model']}`, against the {r['benchmark_queries']} TM11-63 benchmark prompts. "
        "Written by `scripts/eval_hybrid_retrieval.py`.",
        "",
        f"**Chosen:** pool size {r['chosen']['pool_size']} per search, metadata weight "
        f"{r['chosen']['metadata_weight']} (semantic {1 - r['chosen']['metadata_weight']:.1f}), "
        f"k = {r['k']} candidates handed on. **Deterministic:** "
        f"{DETERMINISTIC_YES if r['deterministic'] else 'NO'}.",
        "",
        f"**Retrieval time** (embedding excluded, {r['latency']['hybrid_ms']['runs']} runs): "
        f"before p50 {before['p50']} ms / p95 {before['p95']} ms; "
        f"hybrid p50 {hybrid['p50']} ms / p95 {hybrid['p95']} ms. "
        "Each search opens its own connection, as the API does per request.",
        "",
        "| | hit@3 | hit@10 | hit@20 | MRR | expected titles in top 20 |",
        "|---|---|---|---|---|---|",
        f"| Before (semantic top {r['k']}) | {cells(r['baseline'])} |",
        f"| Hybrid (chosen) | {cells(r['hybrid'])} |",
        "",
        "A hit is any expected title at or above that rank; reference titles never count.",
        "",
        "## Grid: pool size × metadata weight",
        "",
        "hit@10 / MRR for each setting. Weight 0 is semantic order with ruled-out and "
        "named games removed.",
        "",
        "| pool \\ weight | " + " | ".join(str(w) for w in METADATA_WEIGHTS) + " |",
        "|---|" + "---|" * len(METADATA_WEIGHTS),
    ]
    for pool in POOL_SIZES:
        row = [f"{r['grid'][f'{pool}|{w}']['hit@10']} / {r['grid'][f'{pool}|{w}']['mrr']}"
               for w in METADATA_WEIGHTS]
        lines.append(f"| {pool} | " + " | ".join(row) + " |")
    lines += ["", "## By category", "",
              "| Category | Before hit@10 | Hybrid hit@10 | Before MRR | Hybrid MRR |",
              "|---|---|---|---|---|"]
    for cat, m in r["by_category"].items():
        lines.append(f"| {cat} | {m['baseline']['hit@10']}/5 | {m['hybrid']['hit@10']}/5 | "
                     f"{m['baseline']['mrr']} | {m['hybrid']['mrr']} |")
    lines += ["", "## Per prompt", "",
              "| Id | Parsed signals | Before rank | Hybrid rank | Hybrid top 3 |",
              "|---|---|---|---|---|"]
    for q in r["per_query"]:
        p = q["parsed"]
        signals = ", ".join(p["genres"] + p["moods"] + p["platforms"]
                            + [f"like {t}" for t in p["reference_titles"]]) or "—"
        lines.append(f"| {q['id']} | {signals} | {q['baseline_rank'] or '-'} | "
                     f"{q['rank'] or '-'} | {', '.join(q['top_5'][:3])} |")
    gaps = [q for q in r["per_query"]
            if q["named_but_not_recognised"] or not any(q["parsed"].values())]
    if gaps:
        lines += ["", "## Parser gaps this run found", "",
                  "Prompts where the named game wasn't recognised (so it isn't removed from "
                  "the answers) or nothing was parsed (so the prompt ranks on similarity alone). "
                  "These are TM11-62 vocabulary and cue gaps, left for a follow-up rather than "
                  "fitted to these 20 prompts.", "",
                  "| Id | Prompt | Gap |", "|---|---|---|"]
        for q in gaps:
            gap = (f"named {', '.join(q['named_but_not_recognised'])} not recognised"
                   if q["named_but_not_recognised"] else "no signals parsed")
            lines.append(f"| {q['id']} | {q['prompt']} | {gap} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("artifacts/sprint9"))
    args = parser.parse_args()
    if not has_db():
        print("eval_hybrid_retrieval: DATABASE_URL is not set")
        return 2
    report = asyncio.run(evaluate())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "tm11-65-hybrid-retrieval.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8")
    (args.out / "tm11-65-hybrid-retrieval.md").write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
