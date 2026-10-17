# TM11-40 upsert check: writes and updates without duplicates

Local Docker `pgvector/pgvector:pg16`, with every hosted migration in `supabase/migrations/`
applied in order (including `20261018120000_game_embeddings_hnsw_index.sql`) and the
167-game fixture (`scripts/fixtures/games.json`) loaded into `public.games`. Run on
2026-10-17.

| Step | Command | Result |
|---|---|---|
| 1. First embed (writes) | `python scripts/embed_catalogue.py` | 167 embedded, 0 failed. 167 of 167 games have a vector. 5,595 tokens, $0.0000, 20.62 s |
| 2. Re-embed everything (updates) | `python scripts/embed_catalogue.py --all` | 167 embedded, 0 failed. 167 of 167 games have a vector. 5,595 tokens, $0.0000, 17.53 s |
| 3. Count rows | `select count(*), count(distinct (game_id, model)) from public.game_embeddings` | **167 \| 167**: every row was updated in place, none added |

The index existed before step 1, so both runs also wrote into it. The upsert is TM11-39's
`repositories.upsert_game_embeddings` (`on conflict (game_id, model) do update`). This
check confirms it on the real schema with the index in place.
`scripts/eval_vector_index.py` repeats the duplicate check on every run
(`duplicate_rows` in `tm11-40-vector-index.json`).
