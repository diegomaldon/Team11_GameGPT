# TM11-41 re-embed only changed games: real-database check

Local Docker `pgvector/pgvector:pg16` with every hosted migration in `supabase/migrations/`
applied and the 167-game fixture (`scripts/fixtures/games.json`) in `public.games`, already
embedded once with all-MiniLM-L6-v2 (TM11-39). Run on 2026-10-17 with
`python scripts/embed_catalogue.py` and no flags.

| Step | What changed | Summary line | Time |
|---|---|---|---|
| 1. Rerun | Nothing | 0 embedded (0 new, 0 changed), **167 unchanged skipped**, 0 failed. 167 of 167 have a vector. 0 tokens | 0.31 s |
| 2. Rerun | Portal 2's description extended with one sentence (`update public.games ...`) | **1 embedded (0 new, 1 changed), 166 unchanged skipped**, 0 failed. 167 of 167 have a vector. 49 tokens | 15.73 s* |
| 3. Rerun | Nothing | 0 embedded (0 new, 0 changed), **167 unchanged skipped**, 0 failed. 0 tokens | 0.22 s |

\*Most of step 2 is loading the model for the one game. Steps 1 and 3 never load it.

Portal 2's row in `public.game_embeddings`:

| | `document_hash` (first 12) | `embedded_at` |
|---|---|---|
| Before step 2 | `b97577744751` | 2026-10-17 18:27:31 UTC |
| After step 2 | `26072209c3bb` | 2026-10-17 18:42:28 UTC |

After step 3: 167 rows, 167 distinct games. Only Portal 2's row was rewritten.

The full report for step 2 is `tm11-41-modified-game-run.json`
(`changed_count: 1`, `unchanged_skipped: 166`, `embedded_count: 1`, `is_complete: true`).

## Acceptance criteria
- **Content hash per document:** every row's `document_hash` is the SHA-256 of the exact text
  embedded (TM11-39 column). The pipeline recomputes it from the current game row on each run.
- **Unchanged games skipped on re-run:** steps 1 and 3.
- **Verified by re-running with one modified game:** step 2.
