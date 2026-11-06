# GameGPT — Runbook

Operating guide: full local setup, seeding, tests, troubleshooting, and
deployment. For the architecture see [ARCHITECTURE.md](ARCHITECTURE.md).

## Contents
- [Prerequisites](#prerequisites)
- [Full local setup](#full-local-setup)
- [Running the servers](#running-the-servers)
- [Seeding & embeddings](#seeding--embeddings)
- [Enabling real LLM (Gemini/Anthropic)](#enabling-real-llm)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Deployment](#deployment)

---

## Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Node 18+** and npm
- **Docker** (for local Postgres + pgvector)
- ~500 MB disk for `sentence-transformers` + torch (CPU) + the model weights

No API keys are required to run the slice. A `GEMINI_API_KEY` unlocks real
LLM-written recommendations.

---

## Full local setup

```bash
# 0. Config
cp .env.example .env

# 1. Postgres (pgvector)
docker run -d --name gamegpt-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=gamegpt -p 5433:5432 pgvector/pgvector:pg16
export DATABASE_URL="postgresql://postgres:postgres@localhost:5433/gamegpt"

# 2. Python deps
python -m venv .venv
. .venv/Scripts/activate            # Windows Git Bash
# source .venv/bin/activate         # macOS/Linux
pip install -r api/requirements.txt

# 3. Schema + catalogue + demo account (TM11-88), then embed the catalogue
python scripts/seed_demo.py
python scripts/embed_games.py       # local model; downloads ~90 MB on first run
```

Everything is idempotent, so it is safe to rerun. `seed_demo.py` applies the
local migrations itself, so there is no `psql` step. To set up only the
catalogue, `python scripts/seed_games.py` still works on its own (RAWG if keyed).

---

## Running the servers

**API** (from repo root, venv active, `DATABASE_URL` set):
```bash
python -m api.run                   # → http://localhost:8000
```
- The embedding model warms in the background on startup; the first `/api/recommend`
  is ~7s, then fast.
- `HOST`/`PORT` env vars override the bind address (default `0.0.0.0:8000`).

**Web** (separate terminal):
```bash
cd web && npm install && npm run dev  # → http://localhost:3000
```
Set `NEXT_PUBLIC_API_URL` if the API isn't on `http://localhost:8000`.

**Health check:** `curl http://localhost:8000/api/health` → `{"status":"ok",...}`.

---

## Seeding & embeddings

| Script | What it does | Idempotency |
|--------|--------------|-------------|
| `scripts/seed_games.py` | Inserts ~150 games from `scripts/fixtures/games.json` (or RAWG if `RAWG_API_KEY` set) | Upserts on `steam_appid`; re-run = updates, no dupes |
| `scripts/ingest_games.py` + `catalogue_source.py` | Loads the hosted `public.games` from the seed fixture, no RAWG ([TM11-159](#rebuilding-the-hosted-catalogue-without-rawg-tm11-159)) | Upserts on `steam_appid`; identical rows skipped |
| `scripts/steam_catalogue.py` | Grows the hosted catalogue to 1000 games from Steam's most-owned ranking ([TM11-159](#growing-the-hosted-catalogue-to-1000-games-tm11-159)) | Cached; the load is idempotent |
| `scripts/verify_catalogue.py` | Read-only check of the hosted catalogue: size, duplicates, embeddings, benchmark titles | Read-only |
| `scripts/embed_games.py` | Embeds each game's document ([template](embedding-documents.md)) → `embedding` column | Only embeds `NULL` rows; `--all` re-embeds everything |
| `scripts/embed_catalogue.py` | Embeds the Supabase catalogue into `game_embeddings` in batches (TM11-39) | Only games with no vector from the model; `--all` re-embeds everything |
| `scripts/seed_demo.py` | Local schema, the fixture catalogue, and the demo account: linked Steam account, 7-game library, 3 queries with recommendations, 5 votes (TM11-88) | Fixed keys and upserts; `--reset` wipes the account first, `--check` only verifies |
| `supabase/seed.sql` | 5 `owned_games` for the dev user (superseded by `seed_demo.py`) | `ON CONFLICT DO NOTHING` |

**Re-embed after changing the model** (dimension or `EMBEDDING_MODEL`):
```bash
python scripts/embed_games.py --all
```
Existing vectors made by a different model are incompatible — `--all` regenerates
them. If you also changed the dimension, run migration `0002` (or recreate the DB).

### Rebuilding the hosted catalogue without RAWG (TM11-159)

RAWG is down, so the hosted `public.games` is loaded from the committed seed
catalogue, `scripts/fixtures/games.json` (167 games, every TM11-63 benchmark
title), enriched from Steam's public store data. `scripts/catalogue_source.py`
maps it into the rows `ingest_games.py` expects, keyed on `steam_appid`. No API
key is needed.

The Steam details are cached in `.cache/catalogue/steam_appdetails.json`, so
the load itself never calls Steam. The cache is **gitignored** (about 1.3 MB with
the 1000-game data), so a fresh clone has to build it first, about 1.6s per app
to stay under Steam's rate limit. For the seed games only:

```bash
python scripts/steam_store.py              # fetch app ids the cache lacks (~5 min from empty)
python scripts/steam_store.py --refresh    # re-fetch all of them
cd scripts && python -m unittest test_steam_store   # fails if an app id names another game
```

`steam_store.py` also writes the seed games' Steam names to the committed
`scripts/fixtures/steam_seed_names.json`. That small file is what CI checks the
fixture's app ids against; commit it when it changes. Without a cache, the load
stops and says which script to run.

This writes to the shared hosted database. Agree the run with the team first,
and use the **service_role** connection string (`games` is write-restricted by
RLS). Keep `DATABASE_URL` in `.env` only; never paste it into a command line.

```bash
pip install "psycopg[binary]"                        # once; ingest + verify need it
set -a; source .env; set +a                          # DATABASE_URL = hosted, service_role

# 0. Before: note the current state, so the run can be compared against it
python scripts/verify_catalogue.py                   # expect FAIL now (about 16 games)

# 1. Rehearse without touching the database: expect 167 valid, 0 rejected
python scripts/ingest_games.py --source-func catalogue_source:fetch_steam_enriched_catalogue \
    --source steam-seed --target 167 --dry-run --run-id steam-seed-dry-run

# 2. Load the hosted catalogue
python scripts/ingest_games.py --source-func catalogue_source:fetch_steam_enriched_catalogue \
    --source steam-seed --target 167 --run-id steam-seed-01

# 3. Run it again: expect inserted=0 updated=0 unchanged=167 (idempotent)
python scripts/ingest_games.py --source-func catalogue_source:fetch_steam_enriched_catalogue \
    --source steam-seed --target 167 --run-id steam-seed-02

# 4. Embed the new games so search and recommend can return them
python scripts/embed_catalogue.py

# 5. Check: size, duplicates, embeddings, benchmark titles. Exit 0 = all pass
python scripts/verify_catalogue.py
```

- **Reports:** `artifacts/ingestion/<run id>/ingestion_run.md` (counts, duration,
  `rejects.jsonl` with a reason per rejected row), the embedding report under
  `artifacts/embeddings/`, and `artifacts/sprint9/tm11-159-catalogue-check.md`.
- **Idempotent:** the upsert is `ON CONFLICT (steam_appid)` and skips a row whose
  values are identical, so a re-run touches nothing and doesn't churn
  `updated_at` or invalidate embeddings.
- **Rows already there:** the RAWG-era games have a `rawg_id` and no
  `steam_appid`, so they would not hit that conflict. Before each upsert the
  job gives a same-titled row with no `steam_appid` (trimmed, case-insensitive)
  this game's app id, so the seed game updates that row in place and keeps
  its `game_id`, `rawg_id` and library links. Its data columns are replaced by
  the seed + Steam values (so its `XBOX` platform and RAWG tags go), and its
  vector is re-embedded. The run report counts these as **Adopted by title**.
  A RAWG game with no seed counterpart is left as it is.
- **What's loaded:** from the fixture, title, description, genres, tags, release
  date and review score (0–1 scaled to 0–100); from Steam, `critic_score`
  (Metacritic, when Steam has one), publishers, developers, `header_image_url`
  and its categories appended to tags; plus `steam_appid`,
  `available_platforms = {STEAM}` and the Steam store link. Steam doesn't report
  Xbox or Epic availability, so none is claimed; the benchmark's Xbox and Epic
  prompts still need that from another source.
- **App ids:** ten fixture games pointed at other Steam apps (Dinkum's was
  Timberborn's) and Owlboy's didn't exist; TM11-159 corrected them.
  `test_steam_store` compares every Steam name in `steam_seed_names.json` with
  its fixture title, so a wrong id fails CI.
- **Rejected rows:** an entry with no Steam app id, a blank title or a bad score
  is rejected, logged with its reason and written to `rejects.jsonl`; the rest
  still load. Exit code 2 means fewer than `--target` games loaded.
- **Undo:** the load only inserts or updates `games`; it never deletes. To back
  out a bad run, restore from the Supabase daily backup (Database → Backups).

### Growing the hosted catalogue to 1000 games (TM11-159)

`scripts/steam_catalogue.py` adds Steam's most-owned games, in SteamSpy's rank
order, after the 167 seed games until the catalogue holds 1000. Each new game
gets its description, genres, release date, developers, publishers, Metacritic
score and header image from Steam's store data, its tags from SteamSpy's user
tags (highest-voted first) plus Steam's categories, and a `review_score` from
the share of positive Steam reviews (when it has 50+). No key is needed.

```bash
# 1. Fill the caches in .cache/catalogue/ (steamspy_ranking.json, steamspy_tags.json,
#    steam_appdetails.json; gitignored). Fetches the seed games' details too, so it
#    works from an empty cache on a fresh clone. Slow: Steam and SteamSpy are
#    rate-limited, so about 3s per app, ~45 minutes from empty. Safe to stop and
#    rerun; it resumes.
python scripts/steam_catalogue.py --target 1000

# 2-5. Same as the rebuild above, with the larger source and target
python scripts/ingest_games.py --source-func steam_catalogue:fetch_top_steam_catalogue \
    --source steam-top --limit 1000 --target 1000 --dry-run --run-id steam-top-dry-run
python scripts/ingest_games.py --source-func steam_catalogue:fetch_top_steam_catalogue \
    --source steam-top --limit 1000 --target 1000 --run-id steam-top-01
python scripts/ingest_games.py --source-func steam_catalogue:fetch_top_steam_catalogue \
    --source steam-top --limit 1000 --target 1000 --run-id steam-top-02   # expect unchanged=1000
python scripts/embed_catalogue.py
python scripts/verify_catalogue.py --min-games 1000
```

- **Seed games come first and keep their curated text;** a ranked app already in
  the seed fixture is not loaded twice.
- **Skipped apps** are logged and listed with a reason in
  `artifacts/ingestion/steam-catalogue-skips.json`: not a game (DLC, software,
  soundtrack), adult-only (Steam content descriptors 3 and 4), no description,
  unknown to Steam, or a title already in the catalogue.
- **Idempotent:** the load reads only the caches, so re-running it from the same
  cache changes nothing. Re-running step 1 later only fetches apps the cache
  lacks. A cache rebuilt elsewhere (or a newer SteamSpy ranking) can hold newer
  Steam data, so a load from it may report some rows as updated; that is the
  catalogue being refreshed, not duplicated.
- Steam store names are used as titles (for example "Counter-Strike 2"), so a
  RAWG-era row is only adopted when its title matches exactly.

### Embedding the Supabase catalogue (TM11-39)

`embed_games.py` above fills the old `games.embedding` column of the local
`0001_init.sql` slice. The hosted catalogue (`public.games`, filled by
`ingest_games.py`) is embedded into its own table, `public.game_embeddings`, by
`embed_catalogue.py`. Run migration `20261017120000_game_embeddings.sql` first.

```bash
# DATABASE_URL = the Supabase connection string (service role), in .env only
python scripts/embed_catalogue.py                  # new and changed games only
python scripts/embed_catalogue.py --batch-size 64
python scripts/embed_catalogue.py --all            # re-embed every game, e.g. for a new model
```

- **One row per game per model:** model, dimensions, the vector, a SHA-256 of
  the exact text embedded, and its token count. A check keeps `dimensions`
  equal to the vector's real size.
- **Batches and retry:** each batch is tried 3 times, then skipped. Its games
  are listed in the report, and the rest of the catalogue still gets embedded.
- **Resumable:** every batch is saved as soon as it's done. After a failure or
  Ctrl-C, run the same command again; it only picks up games that still need one.
- **Only changed games (TM11-41):** each run hashes the text a game would be
  embedded from and compares it to the stored `document_hash`. A match is skipped,
  so a catalogue refresh only re-embeds the games whose title, description,
  genres or tags changed. The summary and report count `new`, `changed` and
  `unchanged_skipped`.
- **Versioned template (TM11-38):** the text is built by a documented template,
  [docs/embedding-documents.md](embedding-documents.md). Every row stores the
  `template_version` it was embedded with, and a row from an older version
  counts as changed, so bumping the version re-embeds everything without
  `--all`. Run migration `20261020130000_game_embeddings_template_version.sql`
  first.
- **Counted:** each batch logs the running token total and cost (the local
  model is free; an unknown model logs `unknown`). The run ends by counting the
  catalogue against the stored vectors.
- **Report:** `artifacts/embeddings/<run id>/embedding_report.json`. Exit code 0
  means every game has a vector, 1 means some are missing (rerun), and 2 means
  `DATABASE_URL` isn't set.
- **Truncation:** all-MiniLM-L6-v2 reads the first 256 tokens. Longer documents
  are still embedded, from their start, and counted as `truncated_count`.
- `EMBEDDING_STUB=1` stores hash vectors under the model `stub/sha256-hash`, so
  they never mix with real ones.

**Vector index (TM11-40).** Migration `20261018120000_game_embeddings_hnsw_index.sql`
adds the HNSW index for all-MiniLM-L6-v2 rows. It can run before or after the first
embed. To check recall, latency and index size after embedding:

```bash
python scripts/eval_vector_index.py              # writes artifacts/sprint6/tm11-40-vector-index.md
python scripts/eval_vector_index.py --repeats 20
```

It needs the real model (it refuses `EMBEDDING_STUB=1`) and the hosted schema. Exit
code 1 means the index is missing or a `(game_id, model)` row is duplicated.

Both this script and the latency check below score the TM11-63 benchmark, 20 prompts
in `api/fixtures/query_benchmark.json`, each sent with its own platform and genre
filters. See [query-benchmark.md](query-benchmark.md) before changing a prompt.

**Search latency (TM11-42).** To time `POST /api/search` end to end on a warm model,
on either schema:

```bash
python scripts/eval_search_latency.py            # writes artifacts/sprint7/tm11-42-search-latency.md
python scripts/eval_search_latency.py --repeats 20 --k 10
```

It sends requests to the app in-process, so the network hop to a host is not
counted. Exit code 1 means the warm p95 is 1 second or more.

**Recommend latency by stage (TM11-68).** To time parse, embed, retrieve, filter and
rank over the same 20 prompts, without saving anything to the query history:

```bash
python scripts/eval_recommend_latency.py         # writes artifacts/sprint9/tm11-68-recommend-latency.md
```

Without an LLM key, rank times the offline fallback. For deployed numbers, run the
weekly check over the Render logs (`python scripts/latency_report.py render-logs.txt`).
[OBSERVABILITY.md](OBSERVABILITY.md#recommend-latency-by-stage--tm11-68) has the
budgets and what to do with the result.

---

## Enabling real LLM

Embeddings are always local (no key). For real LLM ranking, put a key in `.env`:

```bash
# .env
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-3.6-flash        # optional; this is the default
```
Priority is **Gemini → Anthropic → deterministic stub**. `.env` is loaded
automatically; restart the API to pick up changes. Verify:
```bash
curl -s -X POST http://localhost:8000/api/recommend \
  -H "Content-Type: application/json" -d '{"query":"cozy game"}'
# reasons should be natural sentences, not the "A strong match for…" template
```

---

## Tests

```bash
. .venv/Scripts/activate
python -m pytest api/tests -q
```
- **Without a reachable DB:** the DB-backed tests skip (`test_db_backed.py`,
  `test_seeded_demo_db.py`); everything else runs offline.
- **With `DATABASE_URL` set to a local DB:** `test_seeded_demo_db.py` seeds the
  demo account itself, then reads it back through the API. CI runs the same
  tests in its **Seeded DB tests** job. See the README,
  [Demo data & test harness](../README.md#demo-data--test-harness).
- Tests never hit the network: LLM tests construct services with no keys, and
  embedding tests use the deterministic stub. Set `EMBEDDING_STUB=1` to guarantee
  no model load during tests.

---

## Troubleshooting

**`psycopg … ProactorEventLoop` error / recommend returns 503 on Windows**
Run the API with `python -m api.run` (or `uvicorn api.main:app --reload`), not a
plain `uvicorn`. Windows needs the SelectorEventLoop for psycopg async; `api.run`
sets it. Linux/macOS are unaffected.

**`missing "=" after "https://…supabase.co"` / DB won't connect**
`DATABASE_URL` must be a **Postgres DSN**, not a Supabase HTTPS project URL:
```
# ✅ local docker
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/gamegpt
# ✅ Supabase (Project Settings → Database → Connection string → URI)
DATABASE_URL=postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres
# ❌ not a DSN
DATABASE_URL=https://<ref>.supabase.co
```

**Recommendations are irrelevant / reasons look templated**
You're in offline LLM mode (no `GEMINI_API_KEY`) — ordering is by vector
similarity and reasons are synthesized. Add a key (see above). Also confirm
embeddings used the real model: the seed step must not print
`No sentence-transformers model found…` (that means `EMBEDDING_MODEL` points at a
non-HF name — set it to `sentence-transformers/all-MiniLM-L6-v2` and re-embed).

**Gemini returns 404 / 503**
- 404 "no longer available to new users" → the model id is deprecated for your
  key. Use `gemini-3.6-flash` (default) or list models:
  `GET https://generativelanguage.googleapis.com/v1beta/models?key=…`.
- 503 → transient overload (e.g. the `gemini-flash-latest` alias). `LLMService`
  retries once then falls back to the deterministic ranker.

**`.env` values aren't taking effect**
`.env` is loaded by `api/config.py`. Real environment variables **override**
`.env` (e.g. an exported `DATABASE_URL` wins). `.env` is git-ignored.

**First recommend is slow (~18s)**
Cold model load. The startup warm-up reduces this to ~7s; if you disabled it or
query during boot, the first call pays the load once, then stays warm.

---

## Deployment

Configs are committed; provisioning needs your accounts. Both providers
auto-deploy from `main` once connected.

### API → Render
1. New → Blueprint, point at this repo (`render.yaml` is read automatically).
2. Set env vars per environment (Environment tab): `DATABASE_URL`, `GEMINI_API_KEY`,
   `STEAM_API_KEY`, `DEV_USER_ID`, etc. (`sync: false` vars aren't committed).
3. Auto-deploy is on by default; health check is `/api/health`.

> **Free tier sleeps** after ~15 min idle (~1 min cold start) — upgrade to
> `starter` in `render.yaml` before a live demo, or use a host without cold starts.
> Also note: the API host runs the embedding model in-process, so give it enough
> memory (torch + MiniLM ≈ a few hundred MB).

### Web → Vercel
1. Import the repo; set **Root Directory** to `web`.
2. Add `NEXT_PUBLIC_API_URL` (the Render URL), scoped to Preview + Production.
3. Deployments from `main` are enabled in `web/vercel.json`.

### DB → Supabase
1. Create a project; enable pgvector (the migration does `create extension`).
2. Run `supabase/migrations/0001_init.sql`, then `0002_embedding_dim_384.sql`,
   then `supabase/seed.sql` (SQL editor or `psql`).
3. Run `scripts/seed_games.py` and `scripts/embed_games.py` against the project's
   `DATABASE_URL`.
   For the hosted `public.games` schema, follow
   [Rebuilding the hosted catalogue without RAWG](#rebuilding-the-hosted-catalogue-without-rawg-tm11-159) instead.
