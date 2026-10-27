# TM11-42 semantic search latency

Run 2026-10-23T01:19:42+00:00 on the `legacy` schema with `sentence-transformers/all-MiniLM-L6-v2`, top 10, 20 queries x 10 timed requests each, after one warm-up request per query. Produced by `scripts/eval_search_latency.py`.

| Measure | p50 | p95 | max | runs |
|---|---|---|---|---|
| `POST /api/search`, whole request | 212.24 ms | 826.4 ms | 3198.04 ms | 200 |
| Of which: embed + search (`took_ms`) | 203.83 ms | 818.85 ms | 3190.96 ms | 200 |

Warm p95 **meets** the 1 second budget. The first request after boot, which loads the model, took 40378.27 ms and is not counted.

The expected game was in the top 10 for 7 of 20 queries (the TM11-40 query set).
