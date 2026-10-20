# ADR 0002: Vector store for the RAG pipeline

- **Status:** Accepted. Decided in Sprint 1 (TM11-14), written down in Sprint 6 (TM11-40)
- **Story:** TM11-14 (decision), TM11-40 (index provisioned per this ADR). REQ011
- **Decider:** Noah Merhai

## Context

TM11-14 asked for a vector store decision before any pipeline work started: compare
Supabase pgvector with a hosted vector database on setup cost, ops burden, metadata
filtering and latency, and commit an ADR. The decision was made in Sprint 1 and built into
the schema (`games_embedding_idx`, an HNSW cosine index in
`20260915120200_create_core_tables.sql`), but the ADR itself was never committed. TM11-40's
first acceptance criterion is "index provisioned per the ADR", so this document records
that decision, and the one change TM11-39 forced on it.

## Options

| Option | Setup cost | Ops burden | Metadata filtering | Latency at our size | Verdict |
|---|---|---|---|---|---|
| **A. pgvector in our Supabase Postgres** | None: the extension is already enabled | None extra: same database, backups and RLS | Plain SQL joins to `games`, `owned_games` and their GIN indexes | Sub-millisecond search on our catalogue (see Consequences) | **Chosen** |
| B. Hosted vector DB (Pinecone, Weaviate Cloud) | A new account, API keys, and an ingest job to keep it in sync | A second store to keep consistent with `games`, a second outage to plan for | Only on metadata copied into the vector store | Network round trip to a second service | Rejected |
| C. In-process index (FAISS) | A library, but the index must be rebuilt and shipped with each deploy | Rebuilds on every catalogue change, and not shared between API instances | In Python, after the search | Fast, but every instance holds the whole index | Rejected |

## Decision

**pgvector in the existing Supabase Postgres, with an HNSW index on cosine distance.**

- One fewer service is one fewer thing to fail in a demo, and the catalogue is thousands
  of games, not millions. That's well inside what pgvector handles.
- Retrieval can filter and join in the same query as the search: owned games, platform,
  genre (TM11-43, TM11-58, TM11-65).
- Cosine distance, because all-MiniLM-L6-v2 vectors are normalized
  (`normalize_embeddings=True`).
- HNSW rather than IVFFlat: it can be built on an empty table and needs no retraining as
  games are added. IVFFlat picks its lists from the data present when it is built.

### Change in Sprint 6: one partial index per model

The Sprint 1 index sits on `games.embedding vector(1536)`, which was sized for OpenAI. We
now run all-MiniLM-L6-v2 (384 dimensions), and TM11-39 stores vectors in
`public.game_embeddings`, one row per game per model, with no fixed size. HNSW can only
index one size, so TM11-40 adds a **partial** HNSW index per model:

```sql
create index game_embeddings_minilm_hnsw
  on public.game_embeddings
  using hnsw ((embedding::extensions.vector(384)) extensions.vector_cosine_ops)
  where model = 'sentence-transformers/all-MiniLM-L6-v2';
```

`VectorStore` repeats that cast and model filter in its query so the planner can use it.
Adding a model later means adding its own partial index. It doesn't mean migrating a column.

## Consequences

- Measured in `artifacts/sprint6/tm11-40-vector-index.md` on the 167-game fixture: recall
  20/20 on 20 known queries, Postgres execution under 1 ms, a 344 KB index. At this size the
  planner correctly prefers a sequential scan. The index takes over as the catalogue grows.
- The old `games.embedding` column and `games_embedding_idx` are unused on the hosted
  schema. They are left in place, since dropping them is a separate cleanup.
- Search time end to end is dominated by opening a database connection per request, not by
  the search. Connection pooling is the lever if latency matters (TM11-68, TM11-90).
- Revisit if the catalogue grows past roughly a million vectors, or if we need a vector
  feature pgvector lacks. Neither is likely this semester.
