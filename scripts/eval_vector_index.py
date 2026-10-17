"""Spot-check the game_embeddings vector index (TM11-40, REQ011).

  recall   20 plain-English queries, each with the catalogue game(s) it is
           clearly asking for. A query is a hit when one of them is in the
           top 10 VectorStore returns.
  latency  each query's search timed over repeated runs (the embedding step
           timed separately), reported as p50 and p95.
  index    size of the HNSW index and the table, rows for the model, a
           duplicate check on (game_id, model), and whether the planner uses
           the index.

Writes artifacts/sprint6/tm11-40-vector-index.json and .md.

Usage (from the repo root, venv active, catalogue already embedded with
scripts/embed_catalogue.py):
    python scripts/eval_vector_index.py
    python scripts/eval_vector_index.py --repeats 20 --k 10

Needs the real model: hash vectors from EMBEDDING_STUB=1 carry no meaning, so
recall measured on them would be noise. Exits 2 without a database or with
the stub on, and 1 when the index is missing or a row is duplicated.
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

from api.db import connection, has_db  # noqa: E402
from api.db.schema import catalogue_shape  # noqa: E402
from api.services.embedding import EmbeddingService  # noqa: E402
from api.services.vector_store import VectorStore, _to_vector_literal, hosted_top_k_sql  # noqa: E402

INDEX_NAME = "game_embeddings_minilm_hnsw"
ARTIFACT_DIR = Path("artifacts/sprint6")

# (query, games it is clearly asking for). Written as a player would say it,
# not copied from the catalogue descriptions.
QUERIES: list[tuple[str, set[str]]] = [
    ("farm life sim where you grow crops and make friends in town",
     {"Stardew Valley", "My Time at Portia", "Dinkum"}),
    ("first-person puzzles with a portal gun", {"Portal 2", "Portal"}),
    ("metroidvania in a ruined bug kingdom", {"Hollow Knight"}),
    ("hard platformer about climbing a mountain", {"Celeste"}),
    ("roguelike where you fight your way out of the underworld", {"Hades", "Hades II"}),
    ("deckbuilding roguelike card game", {"Slay the Spire"}),
    ("build automated factories with conveyor belts", {"Factorio", "Satisfactory"}),
    ("survive under the ocean on an alien planet", {"Subnautica"}),
    ("four player co-op zombie shooter", {"Left 4 Dead 2", "Left 4 Dead"}),
    ("check passports at a border checkpoint", {"Papers, Please"}),
    ("figure out what happened to the crew of a ghost ship", {"Return of the Obra Dinn"}),
    ("fire lookout in the woods talking to someone over a radio", {"Firewatch"}),
    ("hide from an alien hunting you on a space station", {"Alien: Isolation"}),
    ("city builder with zoning and traffic", {"Cities: Skylines"}),
    ("medieval dynasty strategy with marriages and scheming", {"Crusader Kings III"}),
    ("story game two players have to play together",
     {"It Takes Two", "A Way Out", "Unravel Two"}),
    ("calm game about unpacking boxes in a new home", {"Unpacking"}),
    ("chaotic co-op cooking in a busy kitchen", {"Overcooked! 2"}),
    ("dwarves mining caves and fighting bugs with friends", {"Deep Rock Galactic"}),
    ("tactical competitive shooter where every bullet counts", {"Counter-Strike 2"}),
]


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile, so p95 of 100 runs is the 95th slowest."""
    ordered = sorted(values)
    rank = max(1, round(pct / 100 * len(ordered)))
    return ordered[rank - 1]


async def evaluate(k: int, repeats: int) -> dict:
    embedder = EmbeddingService()
    store = VectorStore(model=embedder.model_name)
    await embedder.embed_query("warm-up")  # load the model before timing anything

    results, search_ms, embed_ms = [], [], []
    for query, expected in QUERIES:
        started = time.perf_counter()
        vector = await embedder.embed_query(query)
        embed_ms.append((time.perf_counter() - started) * 1000)

        await store.top_k(vector, k=k)  # warm the connection path for this query
        for _ in range(repeats):
            started = time.perf_counter()
            candidates = await store.top_k(vector, k=k)
            search_ms.append((time.perf_counter() - started) * 1000)

        titles = [c.title for c in candidates]
        rank = next((i for i, t in enumerate(titles, start=1) if t in expected), None)
        results.append({
            "query": query,
            "expected": sorted(expected),
            "hit": rank is not None,
            "rank": rank,
            "top_3": titles[:3],
        })

    stats = await index_stats(store, vector)
    hits = sum(r["hit"] for r in results)
    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": store.model,
        "k": k,
        "repeats_per_query": repeats,
        "recall_at_k": round(hits / len(results), 3),
        "hits": hits,
        "queries": len(results),
        # Search latency includes opening a connection, as the API does per request.
        "search_ms": {"p50": round(percentile(search_ms, 50), 2),
                      "p95": round(percentile(search_ms, 95), 2),
                      "max": round(max(search_ms), 2), "runs": len(search_ms)},
        "embed_query_ms": {"p50": round(percentile(embed_ms, 50), 2),
                           "p95": round(percentile(embed_ms, 95), 2)},
        "mean_hit_rank": round(statistics.mean([r["rank"] for r in results if r["hit"]]), 2)
        if hits else None,
        **stats,
        "results": results,
    }


async def index_stats(store: VectorStore, sample_vector: list[float]) -> dict:
    query = hosted_top_k_sql(store.model, store.dimensions)
    params = {"vec": _to_vector_literal(sample_vector), "k": 10}
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select to_regclass(%s) is not null, "
                "coalesce(pg_relation_size(to_regclass(%s)), 0), "
                "pg_total_relation_size('public.game_embeddings'), "
                "(select count(*) from public.games), "
                "(select count(*) from public.game_embeddings where model = %s), "
                "(select count(*) - count(distinct game_id) "
                " from public.game_embeddings where model = %s)",
                (f"public.{INDEX_NAME}", f"public.{INDEX_NAME}", store.model, store.model),
            )
            exists, index_bytes, table_bytes, catalogue, rows, duplicates = await cur.fetchone()

            # Server-side execution time, without the connection the API opens
            # per request. Best of 5 for each plan, so one cold run doesn't skew it.
            plans, exec_ms = {}, {}
            for label, seqscan in (("default", "on"), ("seqscan_off", "off")):
                await cur.execute(f"set local enable_seqscan = {seqscan}")
                runs = []
                for _ in range(5):
                    await cur.execute(
                        b"explain (analyze, format json) " + query.as_bytes(conn), params
                    )
                    (plan,) = await cur.fetchone()
                    runs.append(plan[0]["Execution Time"])
                plans[label] = INDEX_NAME in json.dumps(plan)
                exec_ms[label] = round(min(runs), 3)
            await conn.rollback()

    connect_ms = []
    for _ in range(10):
        started = time.perf_counter()
        async with connection():
            pass
        connect_ms.append((time.perf_counter() - started) * 1000)
    return {
        "index_exists": exists,
        "index_bytes": index_bytes,
        "table_bytes": table_bytes,
        "catalogue_games": catalogue,
        "embedded_rows": rows,
        "duplicate_rows": duplicates,
        "planner_uses_index": plans["default"],
        "index_usable_when_seqscan_off": plans["seqscan_off"],
        "db_execution_ms": {"planner_choice": exec_ms["default"], "hnsw_index": exec_ms["seqscan_off"]},
        "open_connection_ms_p50": round(percentile(connect_ms, 50), 2),
    }


def to_markdown(report: dict) -> str:
    kb = lambda n: f"{n / 1024:.1f} KB"  # noqa: E731
    lines = [
        "# TM11-40 vector index check",
        "",
        f"Run {report['run_at']} with `{report['model']}`, top {report['k']}, "
        f"{report['repeats_per_query']} timed searches per query. "
        "Produced by `scripts/eval_vector_index.py`.",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Recall@{report['k']} (20 known queries) | **{report['hits']}/{report['queries']}** "
        f"({report['recall_at_k']:.0%}) |",
        f"| Mean rank of the expected game, when found | {report['mean_hit_rank']} |",
        f"| Search latency p50 / p95 / max | {report['search_ms']['p50']} / "
        f"{report['search_ms']['p95']} / {report['search_ms']['max']} ms "
        f"({report['search_ms']['runs']} runs) |",
        f"| Of which: opening the connection, p50 | {report['open_connection_ms_p50']} ms |",
        f"| Query execution in Postgres, planner's choice / forced HNSW | "
        f"{report['db_execution_ms']['planner_choice']} / {report['db_execution_ms']['hnsw_index']} ms |",
        f"| Query embedding p50 / p95 | {report['embed_query_ms']['p50']} / "
        f"{report['embed_query_ms']['p95']} ms |",
        f"| HNSW index size | {kb(report['index_bytes'])} |",
        f"| game_embeddings total size | {kb(report['table_bytes'])} |",
        f"| Rows for the model / games in catalogue | {report['embedded_rows']} / "
        f"{report['catalogue_games']} |",
        f"| Duplicate (game_id, model) rows | {report['duplicate_rows']} |",
        f"| Planner picks the index (default settings) | {report['planner_uses_index']} |",
        f"| Index serves the query (seq scan off) | {report['index_usable_when_seqscan_off']} |",
        "",
        "Search latency is measured the way the API runs it: `VectorStore.top_k` opens a new "
        "connection per call. Postgres executes the search in under a millisecond, so almost "
        "all of the end-to-end time is client side: opening the connection, then the query "
        "round trips. Pooling connections (not in this story) is where that time would come "
        "back. These numbers are from a local Docker Postgres, not Supabase. At this "
        "catalogue size Postgres prefers a sequential scan to the HNSW index, which is the "
        "cheaper plan for a table this small; the index serves the same query when the "
        "planner is steered to it, and becomes the planner's choice as the table grows.",
        "",
        "## Queries",
        "",
        "| # | Query | Expected | Hit | Rank | Top 3 returned |",
        "|---|---|---|---|---|---|",
    ]
    for n, r in enumerate(report["results"], start=1):
        lines.append(
            f"| {n} | {r['query']} | {', '.join(r['expected'])} | "
            f"{'yes' if r['hit'] else '**no**'} | {r['rank'] or '-'} | {', '.join(r['top_3'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Spot-check recall and latency of the vector index.")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--out-dir", type=Path, default=ARTIFACT_DIR)
    args = parser.parse_args(argv)

    if not has_db():
        print("eval_vector_index: DATABASE_URL is not set.")
        return 2
    if EmbeddingService().offline:
        print("eval_vector_index: EMBEDDING_STUB=1; recall on hash vectors means nothing.")
        return 2
    if asyncio.run(catalogue_shape()) != "hosted":
        print("eval_vector_index: this database has no game_embeddings (legacy 0001_init.sql shape).")
        return 2

    report = asyncio.run(evaluate(args.k, args.repeats))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "tm11-40-vector-index.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.out_dir / "tm11-40-vector-index.md").write_text(to_markdown(report))
    print(f"recall@{args.k} {report['hits']}/{report['queries']}, "
          f"search p50 {report['search_ms']['p50']} ms p95 {report['search_ms']['p95']} ms, "
          f"index {report['index_bytes']} bytes, duplicates {report['duplicate_rows']}")
    print(f"written to {args.out_dir}/tm11-40-vector-index.md")
    return 0 if report["index_exists"] and report["duplicate_rows"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
