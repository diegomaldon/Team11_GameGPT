"""Time POST /api/search end to end on a warm index (TM11-42, REQ011).

Sends real requests to the app in-process (httpx's ASGI transport), so each
timing covers request validation, embedding the query, opening the database
connection, the vector search and building the response. Only the network hop
to a deployed host is left out.

"Warm" means the model is loaded and each query has been searched once before
timing starts. The first request after boot is reported separately as `cold`.

Writes artifacts/sprint7/tm11-42-search-latency.json and .md.

Usage (from the repo root, venv active, catalogue embedded):
    python scripts/eval_search_latency.py
    python scripts/eval_search_latency.py --repeats 20 --k 10

Needs the real model; EMBEDDING_STUB=1 would time a hash, not the model.
Exits 2 without a database or with the stub on, and 1 when p95 is 1 second or more.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from api.db import has_db  # noqa: E402
from api.db.schema import catalogue_shape  # noqa: E402
from api.main import create_app  # noqa: E402
from eval_vector_index import QUERIES, percentile  # noqa: E402

ARTIFACT_DIR = Path("artifacts/sprint7")
P95_BUDGET_MS = 1000.0


async def evaluate(k: int, repeats: int) -> dict:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        queries = [q for q, _ in QUERIES]

        started = time.perf_counter()
        first = await client.post("/api/search", json={"query": queries[0], "k": k})
        cold_ms = (time.perf_counter() - started) * 1000
        first.raise_for_status()

        for query in queries:  # warm: one untimed search per query
            (await client.post("/api/search", json={"query": query, "k": k})).raise_for_status()

        request_ms, server_ms, hits = [], [], 0
        for query, expected in QUERIES:
            for _ in range(repeats):
                started = time.perf_counter()
                resp = await client.post("/api/search", json={"query": query, "k": k})
                request_ms.append((time.perf_counter() - started) * 1000)
                resp.raise_for_status()
                server_ms.append(resp.json()["took_ms"])
            titles = [r["title"] for r in resp.json()["results"]]
            hits += any(t in expected for t in titles)
        model = resp.json()["model"]

    def summary(values: list[float]) -> dict:
        return {"p50": round(percentile(values, 50), 2), "p95": round(percentile(values, 95), 2),
                "max": round(max(values), 2), "runs": len(values)}

    return {
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "schema": await catalogue_shape(),
        "model": model,
        "k": k,
        "queries": len(QUERIES),
        "repeats_per_query": repeats,
        "cold_first_request_ms": round(cold_ms, 2),
        "request_ms": summary(request_ms),
        "server_took_ms": summary(server_ms),
        "p95_budget_ms": P95_BUDGET_MS,
        "meets_budget": percentile(request_ms, 95) < P95_BUDGET_MS,
        "queries_with_expected_game_in_top_k": hits,
    }


def to_markdown(report: dict) -> str:
    req, srv = report["request_ms"], report["server_took_ms"]
    verdict = "**meets**" if report["meets_budget"] else "**misses**"
    return "\n".join([
        "# TM11-42 semantic search latency",
        "",
        f"Run {report['run_at']} on the `{report['schema']}` schema with `{report['model']}`, "
        f"top {report['k']}, {report['queries']} queries x {report['repeats_per_query']} "
        "timed requests each, after one warm-up request per query. "
        "Produced by `scripts/eval_search_latency.py`.",
        "",
        "| Measure | p50 | p95 | max | runs |",
        "|---|---|---|---|---|",
        f"| `POST /api/search`, whole request | {req['p50']} ms | {req['p95']} ms | "
        f"{req['max']} ms | {req['runs']} |",
        f"| Of which: embed + search (`took_ms`) | {srv['p50']} ms | {srv['p95']} ms | "
        f"{srv['max']} ms | {srv['runs']} |",
        "",
        f"Warm p95 {verdict} the 1 second budget. The first request after boot, "
        f"which loads the model, took {report['cold_first_request_ms']} ms and is not "
        "counted.",
        "",
        f"The expected game was in the top {report['k']} for "
        f"{report['queries_with_expected_game_in_top_k']} of {report['queries']} queries "
        "(the TM11-40 query set).",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()

    if not has_db():
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    if os.environ.get("EMBEDDING_STUB") == "1":
        print("EMBEDDING_STUB=1 would time a hash, not the model", file=sys.stderr)
        return 2

    report = asyncio.run(evaluate(args.k, args.repeats))
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "tm11-42-search-latency.json").write_text(json.dumps(report, indent=2) + "\n")
    (ARTIFACT_DIR / "tm11-42-search-latency.md").write_text(to_markdown(report))
    print(to_markdown(report))
    return 0 if report["meets_budget"] else 1


if __name__ == "__main__":
    sys.exit(main())
