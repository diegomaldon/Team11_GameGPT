# TM11-159 — local rehearsal of the hosted catalogue rebuild

**Not the hosted run.** This is the RUNBOOK procedure run on 2026-11-05 against a
throwaway `pgvector/pgvector:pg16` container holding the hosted `public.games` and
`public.game_embeddings` DDL (from `20260915120200_create_core_tables.sql`,
`20261017120000_game_embeddings.sql`, `20261020130000_game_embeddings_template_version.sql`).
Two RAWG-era rows were inserted first to stand in for the current hosted catalogue:
`Portal 2` (rawg_id 4200, also in the seed) and `Some RAWG Only Game` (rawg_id 9999, not).
Embeddings used `EMBEDDING_STUB=1`, so vectors are `stub/sha256-hash`, not MiniLM.

| Step | Command | Result |
|---|---|---|
| 1. Load | `ingest_games.py --source-func catalogue_source:fetch_seed_catalogue --source steam-seed --target 167` | fetched 167, valid 167, inserted 166, updated 1, rejected 0, target met (exit 0) |
| — | adopted by title | 1: `Portal 2` kept rawg_id 4200 and its game_id, gained steam_appid 620, review_score 98, platforms {STEAM} |
| 2. Re-run | same command | inserted 0, updated 0, **unchanged 167**, rejected 0 (exit 0) |
| — | `select count(*), count(distinct steam_appid), count(distinct lower(title)) from games` | 168, 167, 168: no duplicates |
| 3. Embed | `embed_catalogue.py` (stub) | 168 of 168 embedded, 0 failed |
| 4. Verify | `verify_catalogue.py --model stub/sha256-hash` | **PASS**: 168 games, 0 duplicate appids or titles, 168/168 embedded, 69/69 benchmark titles |

The one game missing a description and steam_appid is the stand-in RAWG-only row,
which the load correctly leaves alone.

Still to do against the hosted Supabase project (needs the service_role
`DATABASE_URL` and team sign-off): the same steps with the real MiniLM model,
committing `artifacts/sprint9/tm11-159-catalogue-check.md` from that run.
