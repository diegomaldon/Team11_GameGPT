# GameGPT — Architecture

A walking skeleton: one vertical slice from the query box to persisted feedback,
with every external dependency behind a service class so it can be faked or
swapped. This document maps the SysML structure diagram to code, traces the
request path, and inventories every stub.

## SysML block → code

Each block in the team's structure diagram is one module with one class. Names
are traceability anchors and are not renamed or merged.

| SysML block      | Class                  | File                                   |
|------------------|------------------------|----------------------------------------|
| Embedding        | `EmbeddingService`     | `api/services/embedding.py`            |
| Vector Store     | `VectorStore`          | `api/services/vector_store.py`         |
| LLM              | `LLMService`           | `api/services/llm.py`                  |
| Deduplication    | `DeduplicationService` | `api/services/deduplication.py`        |
| RAG Pipeline     | `RAGPipeline`          | `api/services/rag_pipeline.py`         |
| Library Sync     | `LibrarySyncService`   | `api/services/library_sync.py`         |

Supporting layers:

| Concern                 | File                                              |
|-------------------------|---------------------------------------------------|
| Wire models (contract)  | `api/models/schemas.py`                           |
| HTTP routers            | `api/routers/{recommend,feedback,library,health}.py` |
| Persistence             | `api/db/repositories.py`                          |
| DB connection + pgvector| `api/db/pool.py`                                  |
| Config / env            | `api/config.py`                                   |
| Schema                  | `supabase/migrations/0001_init.sql`               |
| Seed / embed scripts    | `scripts/{seed_games,embed_games}.py`             |
| Frontend                | `web/app/page.tsx`, `web/lib/api/*`               |

## Request path through the slice

```
web/app/page.tsx  (user types a query, submits)
  └─ web/lib/api/client.ts  recommend(query)
       └─ POST /api/recommend
            └─ api/routers/recommend.py  recommend()
                 ├─ RAGPipeline.recommend(user_id, query)      api/services/rag_pipeline.py
                 │    ├─ EmbeddingService.embed_query(query)    → vector(1536)
                 │    ├─ VectorStore.top_k(embedding, k=20)     → pgvector cosine top-k
                 │    ├─ DeduplicationService.filter_owned(...) → drop games in owned_games
                 │    └─ LLMService.rank(query, candidates, n=3)→ 3 ranked Recommendations
                 ├─ repositories.insert_query(user_id, query)  → queries row (returns query_id)
                 └─ repositories.insert_recommendations(...)   → recommendations rows
            ← RecommendResponse { query_id, query, recommendations[] }
  └─ three cards render (rank, title, reason); user clicks 👍/👎
       └─ web/lib/api/client.ts  sendFeedback({query_id, game_id, title, rank, vote})
            └─ POST /api/feedback
                 └─ api/routers/feedback.py  → repositories.insert_feedback()  → 204

Library:  Steam ID input → client.syncLibrary(steamId) → POST /api/library/sync
            → api/routers/library.py → LibrarySyncService.sync(user_id, steam_id)
              (real Steam IPlayerService/GetOwnedGames call, or seeded fallback)
```

The dev user is a single hardcoded UUID (`config.get_settings().dev_user_id`) —
there is no auth in the skeleton.

## Stub / fake inventory

Everything here is a deliberate skeleton simplification. Each replaces a real
component behind an interface, so swapping it in later is a body change, not a
signature change.

| What is stubbed | Where (file:line) | Real version |
|-----------------|-------------------|--------------|
| **Offline embeddings** — deterministic SHA-256 hashed vector when `OPENAI_API_KEY` is unset. Stable but not semantic. | `api/services/embedding.py:20` (`hashed_embedding`), used at `:65` / `:72` | OpenAI `text-embedding-3-small` (same file, `:76`) |
| **Offline LLM ranking** — takes the top-`n` similarity-ordered candidates and synthesizes a reason. | `api/services/llm.py:33` (`_deterministic_rank`), used at `:90` and as the post-retry fallback `:100` | Anthropic structured-JSON ranking (`api/services/llm.py:102` `_rank_with_llm`) |
| **Steam fallback library** — with no `STEAM_API_KEY`, reuse seeded `owned_games`, or plant a 4-game built-in set. | `api/services/library_sync.py:29` (`_FALLBACK_GAMES`), seed path `:64`–`:75` | Real Steam call `api/services/library_sync.py:82` (`_fetch_steam_games`) — already implemented, needs a key |
| **Catalog seed fallback** — RAWG when keyed, else a committed 150+ game fixture. | `scripts/seed_games.py` (fixture branch); fixture at `scripts/fixtures/games.json` | RAWG API (same script, keyed branch) |
| **No auth** — single seeded dev user, hardcoded UUID. | `api/config.py` (`dev_user_id`); seeded in `supabase/migrations/0001_init.sql` | Google OAuth (out of scope) |
| **Feedback does not affect ranking** — persisted only. | `api/routers/feedback.py` → `repositories.insert_feedback` | Feedback-adjusted ranking (out of scope) |
| **Frontend fixture mode** — `NEXT_PUBLIC_USE_FIXTURES=1` serves canned data with no API. | `web/lib/api/fixtures.ts`, gated in `web/lib/api/client.ts` | Live API calls (default) |
| **Out of scope entirely** — Xbox/Epic integration, game detail pages, purchase links, recommendation history, pagination. | not built | — |

## Deploy topology

- **API** → Render (`render.yaml`), Python/uvicorn, health check `/api/health`.
- **Web** → Vercel (`web/vercel.json`), Next.js, root dir `web`.
- **DB/Vectors** → Supabase Postgres + pgvector (`supabase/migrations`).
- Both auto-deploy from `main`. Env vars are set per environment on each
  provider; nothing secret is committed (`.env.example` holds empty values).
