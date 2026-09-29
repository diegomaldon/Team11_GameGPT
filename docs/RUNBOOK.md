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

# 2. Migrations + owned-games seed (idempotent, in order)
docker exec -i gamegpt-pg psql -U postgres -d gamegpt < supabase/migrations/0001_init.sql
docker exec -i gamegpt-pg psql -U postgres -d gamegpt < supabase/migrations/0002_embedding_dim_384.sql
docker exec -i gamegpt-pg psql -U postgres -d gamegpt < supabase/seed.sql

# 3. Python deps
python -m venv .venv
. .venv/Scripts/activate            # Windows Git Bash
# source .venv/bin/activate         # macOS/Linux
pip install -r api/requirements.txt

# 4. Seed the catalog + embed it (idempotent; re-runnable)
python scripts/seed_games.py        # 150 games from the fixture (or RAWG if keyed)
python scripts/embed_games.py       # local model; downloads ~90 MB on first run
```

The `docker exec ... < file` redirect is Bash/PowerShell syntax; in cmd.exe use
`psql -f`. Everything is idempotent — safe to re-run.

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
| `scripts/embed_games.py` | Embeds `title + description + genres` → `embedding` column | Only embeds `NULL` rows; `--all` re-embeds everything |
| `supabase/seed.sql` | 5 `owned_games` for the dev user | `ON CONFLICT DO NOTHING` |

**Re-embed after changing the model** (dimension or `EMBEDDING_MODEL`):
```bash
python scripts/embed_games.py --all
```
Existing vectors made by a different model are incompatible — `--all` regenerates
them. If you also changed the dimension, run migration `0002` (or recreate the DB).

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
- **Without a reachable DB:** 13 passed, 2 skipped (the pgvector/dedup tests skip).
- **With `DATABASE_URL` set to a live DB:** 15 passed.
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
