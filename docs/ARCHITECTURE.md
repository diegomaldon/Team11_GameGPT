# GameGPT — Architecture

A walking skeleton: one vertical slice from the query box to persisted feedback,
with every external dependency behind a service class so it can be faked or
swapped. This document maps the SysML structure diagram to code, traces the
request path, describes the data model and providers, and inventories every stub.

## Contents
- [SysML block → code](#sysml-block--code)
- [Request path](#request-path-through-the-slice)
- [Data model](#data-model)
- [Providers](#providers)
- [Configuration & startup](#configuration--startup)
- [Stub / fallback inventory](#stub--fallback-inventory)
- [Deploy topology](#deploy-topology)

---

## SysML block → code

Each block in the team's structure diagram is one module with one class. Names
are traceability anchors and are not renamed or merged.

| SysML block   | Class                  | File                              |
|---------------|------------------------|-----------------------------------|
| Embedding     | `EmbeddingService`     | `api/services/embedding.py`       |
| Vector Store  | `VectorStore`          | `api/services/vector_store.py`    |
| LLM           | `LLMService`           | `api/services/llm.py`             |
| Deduplication | `DeduplicationService` | `api/services/deduplication.py`   |
| RAG Pipeline  | `RAGPipeline`          | `api/services/rag_pipeline.py`    |
| Library Sync  | `LibrarySyncService`   | `api/services/library_sync.py`    |

Supporting layers:

| Concern                  | File                                   |
|--------------------------|----------------------------------------|
| Wire models (contract)   | `api/models/schemas.py`                |
| HTTP routers             | `api/routers/{recommend,search,feedback,library,health}.py` |
| Retrieval on its own     | `api/services/semantic_search.py` (TM11-42) |
| Persistence              | `api/db/repositories.py`               |
| DB connection + pgvector | `api/db/pool.py`                       |
| Config / env / .env      | `api/config.py`                        |
| App factory + warm-up    | `api/main.py`                          |
| Windows launcher         | `api/run.py`                           |
| Schema                   | `supabase/migrations/`                 |
| Seed / embed scripts     | `scripts/{seed_games,embed_games}.py`  |
| Frontend                 | `web/`                                 |

---

## Request path through the slice

### Recommend

```
web/app/(app)/page.tsx  (user submits a query)
  └─ web/lib/api/client.ts  recommend(query)
       └─ POST /api/recommend
            └─ api/routers/recommend.py  recommend()
                 ├─ RAGPipeline.recommend(user_id, query)         api/services/rag_pipeline.py
                 │    ├─ EmbeddingService.embed_query(query)       → 384-dim vector (local HF)
                 │    ├─ VectorStore.top_k(embedding, k=20)        → pgvector cosine top-k
                 │    ├─ DeduplicationService.filter_owned(...)    → drop games in owned_games
                 │    └─ LLMService.rank(query, candidates, n=3)   → 3 ranked Recommendations (Gemini)
                 ├─ repositories.insert_query(user_id, query)      → queries row (returns query_id)
                 └─ repositories.insert_recommendations(...)       → recommendations rows
            ← RecommendResponse { query_id, query, recommendations[] }
  └─ three cards render (rank, title, reason, score, Steam link); user clicks 👍/👎
       └─ web/lib/api/client.ts  sendFeedback({query_id, game_id, title, rank, vote})
            └─ POST /api/feedback → repositories.insert_feedback() → 204
```

### Semantic search (TM11-42)

```
POST /api/search { query, k }
  └─ api/routers/search.py  semantic_search()
       └─ SemanticSearchService.search(query, k)      api/services/semantic_search.py
            ├─ EmbeddingService.embed_query(query)     → 384-dim vector
            └─ VectorStore.top_k(embedding, k)         → cosine top-k (same SQL as recommend)
  ← SemanticSearchResponse { query, k, model, results[rank, game_id, title, similarity, …], took_ms }
```

The first two steps of recommend, without dropping owned games, the LLM or any
writes. Retrieval can be tested, timed (`scripts/eval_search_latency.py`) and
tuned apart from ranking.

### Library sync

```
POST /api/library/sync (steamID64)
  └─ api/routers/library.py → LibrarySyncService.sync(user_id, steam_id)
       ├─ STEAM_API_KEY set  → real Steam IPlayerService/GetOwnedGames → upsert owned_games (source="steam")
       └─ no key             → reuse seeded owned_games, else built-in fallback (source="seed")
```

The dev user is a single hardcoded UUID (`config.get_settings().dev_user_id`) —
there is no real auth in the API.

---

## Data model

Postgres schema (`supabase/migrations/0001_init.sql`, dims updated by `0002`):

| Table | Purpose | Notable columns |
|-------|---------|-----------------|
| `users` | Seeded dev user (no auth) | `id`, `email` |
| `games` | Knowledge base | `title`, `description`, `genres[]`, `tags[]`, `release_date`, `developer`, `review_score`, `steam_appid`, **`embedding vector(384)`** |
| `platform_accounts` | Linked platform accounts | `user_id`, `platform`, `external_id` |
| `owned_games` | Cross-platform library (dedup source) | `user_id`, `game_id`, `platform`, `steam_appid`, `title` |
| `queries` | One row per recommend call | `user_id`, `text` |
| `recommendations` | Ranked results per query | `query_id`, `game_id`, `rank`, `title`, `reason` |
| `recommendation_feedback` | Thumbs up/down (persisted only) | `query_id`, `game_id`, `title`, `rank`, `vote` |

`games.embedding` is a **384-dim** `vector` (Hugging Face `all-MiniLM-L6-v2`),
indexed with an IVFFlat cosine index. Migration `0002_embedding_dim_384.sql`
migrates a DB created before the switch from OpenAI's 1536-dim column (it clears
incompatible vectors and requires a re-embed).

On the hosted Supabase schema, vectors live in their own table,
**`game_embeddings`** (TM11-39): one row per `(game_id, model)` with `dimensions`,
`embedding`, `document_hash` and `token_count`. `scripts/embed_catalogue.py` fills
it in batches (see RUNBOOK). TM11-40 indexes it: a partial HNSW cosine index per model,
`game_embeddings_minilm_hnsw` on `(embedding::vector(384)) where model =
'sentence-transformers/all-MiniLM-L6-v2'` (decision: `docs/adr/0002-vector-store.md`).

Incremental runs (TM11-41): each run re-embeds only new games and games whose
`document_hash` no longer matches their current text; unchanged games are skipped.

---

## Providers

### Embeddings — local Hugging Face (`EmbeddingService`)
- Runs `sentence-transformers/all-MiniLM-L6-v2` **locally** (384-dim). No API key,
  works offline; downloads ~90 MB once, cached on the class per process.
- CPU-bound `encode()` runs off the event loop via `asyncio.to_thread`.
- **Fallback:** a deterministic SHA-256 hashed vector when `EMBEDDING_STUB=1` or
  sentence-transformers/torch is unavailable (keeps tests fast and dependency-free).

### LLM ranking — Gemini → Anthropic → stub (`LLMService`)
- **Preferred:** Google Gemini via httpx REST (`generateContent`, `responseMimeType:
  application/json`), default model `gemini-3.6-flash`.
- **Fallback 1:** Anthropic (`anthropic` SDK) when `ANTHROPIC_API_KEY` is set.
- **Fallback 2:** a deterministic ranking (top-n by similarity, synthesized
  reason) when no key is set or all providers fail.
- Each real provider gets **one retry** on a parse/validation failure; output is
  validated into `Recommendation` models. Provider errors are swallowed inside
  `rank()` (so the Gemini URL, which carries the key as a query param, never
  reaches logs).

### Vector search (`VectorStore`)
- pgvector cosine search ordered by distance ascending, `k=20`.
  `similarity = 1 − distance`, clamped to `[0, 1]`.
- Reads whichever schema `DATABASE_URL` has (`api/db/schema.py`, checked once per
  process): on **hosted** Supabase it searches `game_embeddings` joined to `games`,
  filtered to the configured model and cast to its size so the partial HNSW index
  can serve it (TM11-40). On the **legacy** `0001_init.sql` slice it searches
  `games.embedding` as before. `DeduplicationService` follows the same switch
  (see below).

### Ownership (`DeduplicationService`, TM11-58)
- `check_ownership(user_id, game)` → `Ownership(game_id, platforms)`: whether the
  user owns the game on any linked platform, and which ones (REQ008 badges).
- `owned_platforms(user_id, games)` → `{game_id: ("steam", "xbox", ...)}` for every
  owned game in the list, in one query. Unowned games are left out. Platforms are
  lowercase, in the web library's `PLATFORM_ORDER` (steam, xbox, epic, playstation,
  then anything else alphabetically).
- `filter_owned(user_id, candidates)` drops every game `owned_platforms` reports,
  keeping input order (REQ007). Recommend uses it, so a game is never both badged
  as owned and recommended.
- **Hosted:** matches on `owned_games.game_id`; the platform comes from the joined
  `platform_accounts` row. **Legacy:** matches on `game_id`, `steam_appid` or
  title, platform from `owned_games.platform`, and unions the platforms
  from every key that matches.
- **Title normalisation (TM11-57):** titles are compared by
  `title_matching.ownership_key`. It folds case, accents, punctuation,
  apostrophes, `&`, trademark symbols (™ ® © ℠), edition suffixes (Definitive,
  Game of the Year, Special, Ultimate, Director's Cut, ...) and a trailing
  remaster marker (Remastered, HD Remaster). It is looser than the import
  matcher on purpose: an import keeps a remaster as its own `games` row, but
  REQ007 errs on the side of hiding, so owning either one hides the other.
  `api/tests/test_deduplication.py` holds the 40-pair fixture set.
- **Accepted false positives** (hidden although arguably a different purchase;
  pinned in `test_deduplication.py`):
  - Original and remaster hide each other (*BioShock* / *BioShock Remastered*).
  - Owning the base game hides its bundle editions (*The Witcher 3* hides
    *Complete Edition*), even though the bundle adds DLC.
  - Enhanced editions fold into the original (*Baldur's Gate: Enhanced Edition*).
  - Legacy only: two different games with the same title hide each other even
    when their appids differ (*Doom* 1993 / *DOOM* 2016), because every match
    key is unioned.
- **Accepted false negatives** (still recommended although owned):
  - Hosted only: an owned edition with its own `games` row does not hide the
    base game's row, since hosted matches `game_id` only. Pinned as a strict
    xfail.
  - Edition names without a trailing "Edition", "Cut" or "Version" are kept
    apart (*Persona 5 Royal*, *The Stanley Parable: Ultra Deluxe*), as are
    remakes (*Final Fantasy VII Remake*).
- Recall, latency and index size: `scripts/eval_vector_index.py` →
  `artifacts/sprint6/tm11-40-vector-index.md`.

### Steam (`LibrarySyncService`)
- Real `IPlayerService/GetOwnedGames` call via httpx (needs only an API key +
  public steamID64, no OAuth). The one external call is isolated with an
  injectable client so it can be faked. Seeded fallback when no key.

---

## Configuration & startup

- **`api/config.py`** loads `.env` at the repo root via `python-dotenv`
  (`override=False`, so real env vars win), then reads settings from `os.environ`.
  This is why keys land in the process for the API, seed scripts, and tests
  without a manual `export`.
- **`api/main.py`** is the app factory: CORS for `localhost:3000`, routers, and a
  **lifespan startup that warms the embedding model in the background** so the
  first recommend request doesn't pay the one-time model-load cost.
- **`api/run.py`** installs the `WindowsSelectorEventLoopPolicy` before starting
  uvicorn so psycopg's async driver works on Windows (no-op on Linux/macOS, the
  deploy target). `api/__init__.py` sets the same policy at import for scripts/tests.
- **`api/db/pool.py`** opens async psycopg connections and registers the pgvector
  adapter in one place; `has_db()` gates DB-dependent paths.

---

## Stub / fallback inventory

Deliberate skeleton simplifications. Each replaces a real component behind an
interface, so swapping it in later is a body change, not a signature change.

| What | Where | Real version |
|------|-------|--------------|
| **Deterministic hash embedding** — `EMBEDDING_STUB=1` / no torch | `api/services/embedding.py` (`hashed_embedding`) | Local HF model (same file, `_encode`) |
| **Deterministic LLM ranking** — no LLM key or all providers fail | `api/services/llm.py` (`_deterministic_rank`) | Gemini (`_rank_with_gemini`) / Anthropic (`_rank_with_anthropic`) |
| **Steam seeded fallback** — no `STEAM_API_KEY` | `api/services/library_sync.py` (`_FALLBACK_GAMES`, seed path) | Real Steam call (`_fetch_steam_games`) |
| **Catalog fixture** — no `RAWG_API_KEY` | `scripts/seed_games.py` + `scripts/fixtures/games.json` | RAWG API (same script) |
| **No auth** — single seeded dev user | `api/config.py` `dev_user_id`; seeded in `0001_init.sql` | Google OAuth (out of scope) |
| **Feedback doesn't affect ranking** — persisted only | `api/routers/feedback.py` | Feedback-adjusted ranking (out of scope) |
| **Front-end auth / library / account linking** — localStorage mock | `web/lib/mock/*`, `web/app/signin`, `web/app/(app)/{library,settings}` | Real auth + platform OAuth + import (out of scope) |
| **Front-end fixture mode** — `NEXT_PUBLIC_USE_FIXTURES=1` | `web/lib/api/fixtures.ts` | Live API calls (default) |
| **Out of scope entirely** — Xbox/Epic/PS import, game detail pages, purchase links, history, pagination | not built | — |

---

## Deploy topology

- **API** → Render (`render.yaml`), Python/uvicorn, health check `/api/health`.
- **Web** → Vercel (`web/vercel.json`), Next.js, root dir `web`.
- **DB / vectors** → Supabase Postgres + pgvector (`supabase/migrations`).
- Both auto-deploy from `main`. Env vars are set per environment on each provider;
  nothing secret is committed (`.env.example` holds empty values). Embeddings run
  in-process on the API host (no embedding service to provision).
