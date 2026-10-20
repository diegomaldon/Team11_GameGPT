-- =============================================================================
-- GameGPT :: 20261018120000 :: game_embeddings HNSW index
-- TM11-40 Provision vector index and upsert embeddings (REQ011)
-- AC: index provisioned per the ADR (docs/adr/0002-vector-store.md)
-- =============================================================================
--
-- Cosine HNSW index over the all-MiniLM-L6-v2 rows of public.game_embeddings
-- (TM11-39). That table's `embedding` column has no fixed size, because it can
-- hold vectors from more than one model, and HNSW only indexes a fixed size. So
-- the index casts to vector(384) and covers only this model's rows.
--
-- A query uses it only when it repeats both the cast and the model filter:
--
--   where e.model = 'sentence-transformers/all-MiniLM-L6-v2'
--   order by e.embedding::extensions.vector(384) <=> '[...]'::extensions.vector(384)
--   limit k
--
-- api/services/vector_store.py writes exactly that. A different model needs its
-- own partial index with its own size.
--
-- m and ef_construction stay at pgvector's defaults (16, 64): they are tuned
-- for far larger tables than our catalogue. Recall and latency are recorded in
-- artifacts/sprint6/tm11-40-vector-index.md.
--
-- Guarded like 20261017120000: a dev box built from 0001_init.sql has no
-- game_embeddings table and keeps using games.embedding.
-- =============================================================================

do $$
begin
  if to_regclass('public.game_embeddings') is not null then
    create index if not exists game_embeddings_minilm_hnsw
      on public.game_embeddings
      using hnsw ((embedding::extensions.vector(384)) extensions.vector_cosine_ops)
      where model = 'sentence-transformers/all-MiniLM-L6-v2';

    comment on index public.game_embeddings_minilm_hnsw is
      'Cosine HNSW over all-MiniLM-L6-v2 rows (TM11-40). Queries must cast to vector(384) and filter on model.';
  end if;
end
$$;
