# TM11-68 recommend latency by stage

Run 2026-11-05T15:04:15+00:00 on the local `hosted` schema: 20 benchmark prompts x 5 runs each, after one warm-up run. Rank used the offline fallback (no LLM key), so its numbers are not a model's. Produced by `scripts/eval_recommend_latency.py`.

100 finished requests. Failed: none.

| Stage | p50 | p95 | p95 budget | Within budget |
|---|---|---|---|---|
| parse | 0.2 ms | 0.2 ms | 250.0 ms | yes |
| embed | 10.0 ms | 11.9 ms | 250.0 ms | yes |
| retrieve | 13.1 ms | 15.8 ms | 750.0 ms | yes |
| filter | 10.4 ms | 12.9 ms | 500.0 ms | yes |
| rank | 0.0 ms | 0.0 ms | 7500.0 ms | yes |
| total | 33.6 ms | 39.8 ms | 10000.0 ms | yes |
