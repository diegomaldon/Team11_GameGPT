# GameGPT

**CIS454 — Software Implementation Project.** A cross-platform game-discovery
app: link your gaming accounts, describe a vibe in natural language, and get 3–5
ranked recommendations from a RAG pipeline over a game knowledge base — with the
games you already own filtered out, and thumbs up/down feedback.

This repository is a **working walking skeleton**: one vertical slice built end
to end, from a real UI down to a real database, with every external dependency
behind a swappable service class.

```
query box → POST /api/recommend → embed (local HF) → pgvector top-k → drop owned
          → Gemini ranks 3 → persist → render cards → 👍/👎 → POST /api/feedback
```

---

## Table of contents

- [Current status](#current-status)
- [Tech stack](#tech-stack)
- [Architecture at a glance](#architecture-at-a-glance)
- [Quickstart (local)](#quickstart-local)
- [Project structure](#project-structure)
- [Environment variables](#environment-variables)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Known issues & caveats](#known-issues--caveats)

---

## Current status

| Area | State |
|------|-------|
| **Recommendation slice** (query → recommend → feedback) | ✅ Working end to end against Postgres |
| **Embeddings** | ✅ Local Hugging Face `all-MiniLM-L6-v2` (384-dim), no key, offline |
| **LLM ranking** | ✅ Google **Gemini** (`gemini-3.6-flash`); Anthropic → deterministic stub fallbacks |
| **Library sync (Steam)** | ✅ Real Steam Web API path + seeded fallback |
| **Web app** | ✅ Sign-in, Discover, Library, Settings (see note) |
| **Persistence** | ✅ `queries`, `recommendations`, `recommendation_feedback` rows written |
| **Tests** | ✅ `pytest` 15 passed w/ DB · 13 passed + 2 skipped w/o |
| **Deployment (Render/Vercel/Supabase)** | ⏳ Configured, not yet provisioned — needs your accounts |

**Web app note:** the **Discover** page is fully live (hits the API + recommender).
**Sign-in, Library, and account linking (Steam/Xbox/Epic/PlayStation) are a
front-end mock** backed by browser `localStorage` — they demonstrate the full
product UI without a real auth/accounts backend, which is out of scope for the
skeleton. See [docs/FRONTEND.md](docs/FRONTEND.md).

---

## Tech stack

| Layer | Choice |
|-------|--------|
| API | Python 3.11+, FastAPI, Pydantic v2, uvicorn |
| Database | Postgres + [pgvector](https://github.com/pgvector/pgvector) (Supabase-compatible) |
| Embeddings | Hugging Face `sentence-transformers/all-MiniLM-L6-v2` (local, 384-dim) |
| LLM | Google Gemini (`gemini-3.6-flash`) → Anthropic → deterministic stub |
| Web | Next.js 15 (App Router), TypeScript, Tailwind CSS |
| Catalog source | RAWG API (with a committed 150-game fixture fallback) |
| Deploy targets | Render (API) · Vercel (web) · Supabase (DB) |

Every external call (LLM, Steam, RAWG, DB) lives behind a service class so it can
be faked in tests and swapped without touching callers.

---

## Architecture at a glance

Six services map one-to-one to the team's SysML structure diagram (names are a
grading/traceability anchor — do not rename):

| SysML block | Class | File |
|-------------|-------|------|
| Embedding | `EmbeddingService` | `api/services/embedding.py` |
| Vector Store | `VectorStore` | `api/services/vector_store.py` |
| LLM | `LLMService` | `api/services/llm.py` |
| Deduplication | `DeduplicationService` | `api/services/deduplication.py` |
| RAG Pipeline | `RAGPipeline` | `api/services/rag_pipeline.py` |
| Library Sync | `LibrarySyncService` | `api/services/library_sync.py` |

Full request path, data model, and stub inventory: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

---

## Quickstart (local)

You need **Python 3.11+**, **Node 18+**, and **Docker** (for Postgres). No API
keys are required — the slice runs with local embeddings and a deterministic LLM
fallback. Add a `GEMINI_API_KEY` for real LLM-written recommendations.

### 1. Clone & configure

```bash
cp .env.example .env
# Optional: put GEMINI_API_KEY=... in .env for Gemini-written reasons.
```

### 2. Start Postgres (pgvector) + migrate + seed

```bash
docker run -d --name gamegpt-pg -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=gamegpt -p 5433:5432 pgvector/pgvector:pg16

export DATABASE_URL="postgresql://postgres:postgres@localhost:5433/gamegpt"

# migrations (idempotent, in order)
docker exec -i gamegpt-pg psql -U postgres -d gamegpt < supabase/migrations/0001_init.sql
docker exec -i gamegpt-pg psql -U postgres -d gamegpt < supabase/migrations/0002_embedding_dim_384.sql
docker exec -i gamegpt-pg psql -U postgres -d gamegpt < supabase/seed.sql
```

### 3. API + recommender

```bash
python -m venv .venv && . .venv/Scripts/activate     # Windows Git Bash
#                       source .venv/bin/activate     # macOS/Linux
pip install -r api/requirements.txt

python scripts/seed_games.py      # 150 games from the fixture (or RAWG if keyed)
python scripts/embed_games.py     # local model; downloads ~90 MB on first run

python -m api.run                 # → http://localhost:8000/api/health
```

> **Windows:** use `python -m api.run` (or `uvicorn api.main:app --reload`).
> A plain `uvicorn` picks the ProactorEventLoop, which psycopg's async driver
> can't use. On Linux/macOS `uvicorn api.main:app` works directly.

### 4. Web app

```bash
cd web
npm install
npm run dev                       # → http://localhost:3000
```

Open **http://localhost:3000**, sign in (demo — any details), and query on the
Discover page. The full runbook (troubleshooting, keys, fixtures) is in
**[docs/RUNBOOK.md](docs/RUNBOOK.md)**.

---

## Project structure

```
api/                     FastAPI service
  main.py                app factory, CORS, startup model warm-up
  run.py                 Windows-safe launcher (SelectorEventLoop)
  config.py              env/.env loading (python-dotenv)
  models/schemas.py      Pydantic request/response contract
  routers/               health, recommend, feedback, library
  services/              the 6 SysML blocks (see table above)
  db/pool.py             async psycopg connection + pgvector registration
  db/repositories.py     persistence (queries, recommendations, feedback, owned)
  fixtures/              Phase-0 recommendation fixture
  tests/                 pytest (services + pipeline; DB tests skip when no DB)
web/                     Next.js App Router frontend
  app/(app)/             authenticated shell: Discover / Library / Settings
  app/signin/            sign-in page
  components/            AppShell, UI primitives, icons
  lib/api/               typed client + generated OpenAPI types + fixtures
  lib/mock/              localStorage-backed mock store (auth/library/accounts)
scripts/                 seed_games.py, embed_games.py, games.json fixture
supabase/                migrations/ (0001 init, 0002 384-dim) + seed.sql
docs/                    ARCHITECTURE, API, FRONTEND, RUNBOOK, skeleton brief
openapi.json             generated API contract (source for web types)
render.yaml              Render blueprint (API)
web/vercel.json          Vercel config (web)
```

---

## Environment variables

Copy `.env.example` → `.env`. `.env` is loaded automatically (via
`python-dotenv`) for the API, scripts, and tests. **No secret is ever committed.**

| Variable | Purpose | Blank / default behavior |
|----------|---------|--------------------------|
| `DATABASE_URL` | Postgres DSN | Required for the full slice |
| `GEMINI_API_KEY` | Gemini LLM ranking | Falls back to Anthropic, then a deterministic stub |
| `GEMINI_MODEL` | Gemini model id | `gemini-3.6-flash` |
| `ANTHROPIC_API_KEY` | Fallback LLM | Falls back to deterministic stub |
| `EMBEDDING_MODEL` | HF model id | `sentence-transformers/all-MiniLM-L6-v2` |
| `EMBEDDING_STUB` | Force deterministic hash embeddings | `1` skips torch (used in tests) |
| `STEAM_API_KEY` | Steam library sync | `/api/library/sync` returns seeded rows |
| `RAWG_API_KEY` | Catalog source | `seed_games.py` uses the committed fixture |
| `DEV_USER_ID` | Single seeded dev user (no auth) | `00000000-…-0001` |
| `NEXT_PUBLIC_API_URL` | Web → API base URL | `http://localhost:8000` |
| `NEXT_PUBLIC_USE_FIXTURES` | Web fixture mode (no API) | `1` serves canned data |

---

## Deployment

Both providers auto-deploy from `main` once connected — no manual step per push.
Configs are committed; provisioning requires your accounts.

- **API → Render** — `render.yaml` blueprint; start `uvicorn api.main:app`,
  health `/api/health`. Set env vars per environment in the dashboard.
- **Web → Vercel** — root dir `web`; set `NEXT_PUBLIC_API_URL`.
- **DB → Supabase** — run `supabase/migrations/*` then the seed scripts against
  the project's Postgres.

> Render's free tier sleeps after ~15 min idle (~1 min cold start) — upgrade to
> `starter` before a live demo. See [docs/RUNBOOK.md](docs/RUNBOOK.md#deployment).

---

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | SysML→code map, request path, data model, provider details, stub inventory |
| [docs/API.md](docs/API.md) | Every endpoint: method, body, response, examples |
| [docs/FRONTEND.md](docs/FRONTEND.md) | Web routes, design system, mock store, API client, fixture mode |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Full local setup, seeding, tests, troubleshooting, deployment |
| [docs/skeleton.txt](docs/skeleton.txt) | The original scope brief this was built from |

---

## Known issues & caveats

- **`.env` `DATABASE_URL` format** — must be a Postgres DSN
  (`postgresql://user:pass@host:port/db`), **not** a Supabase HTTPS project URL.
  See [docs/RUNBOOK.md](docs/RUNBOOK.md#troubleshooting).
- **First recommend is ~7s** — the embedding model loads once per process (warmed
  on startup); subsequent calls are dominated by Gemini latency.
- **Offline LLM mode** — with no `GEMINI_API_KEY`/`ANTHROPIC_API_KEY`, ranking
  uses a deterministic stub: it works and persists, but reasons are templated and
  ordering is by vector similarity only.
- **Gemini model names change** — `gemini-2.5-flash`/`gemini-flash-latest` were
  deprecated/unavailable for this key; `gemini-3.6-flash` is the current default.
- **Auth/linking is mocked** in the web app (localStorage) — see the status note.
- **Not yet deployed** — deployment acceptance criteria depend on your
  Render/Vercel/Supabase accounts.
