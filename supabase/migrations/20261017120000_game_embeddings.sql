-- =============================================================================
-- GameGPT :: 20261017120000 :: game_embeddings
-- TM11-39 Batch embedding generation pipeline (REQ011)
-- AC: model name and dimensions recorded per row
-- =============================================================================
--
-- One vector per game per model, written by api/services/embedding_pipeline.py.
--
-- Why a table and not games.embedding: that column is vector(1536), sized for
-- OpenAI, but the model we run (all-MiniLM-L6-v2) makes 384-dim vectors. Here
-- `embedding` has no fixed size, and `dimensions` records it per row. A check
-- keeps the two in step, so a row can't claim a size its vector doesn't have.
--
--   (game_id, model)  primary key: re-embedding replaces the row, never adds one
--   document_hash     SHA-256 of the exact text embedded; TM11-41 compares it to
--                     skip games whose text hasn't changed
--   token_count       tokens in that text, for the run's cost log
--
-- No similarity index here: that is TM11-40 (index per the vector store ADR).
-- An HNSW index needs a fixed size, so it can index one model's rows, e.g.
-- ((embedding::extensions.vector(384))) where model = '<model>'.
--
-- RLS on with no policies: only the service role (the API and the batch job)
-- reads or writes it. Clients never need raw vectors.
--
-- Guarded like 20261012120000: only the hosted shape of games has game_id.
-- A dev box built from 0001_init.sql keeps using games.embedding.
-- =============================================================================

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'games' and column_name = 'game_id'
  ) then
    create table if not exists public.game_embeddings (
      game_id        uuid not null references public.games (game_id) on delete cascade,
      model          text not null,
      dimensions     smallint not null,
      embedding      extensions.vector not null,
      document_hash  text not null,
      token_count    integer not null,
      embedded_at    timestamptz not null default now(),

      primary key (game_id, model),
      constraint game_embeddings_model_not_blank check (length(btrim(model)) > 0),
      constraint game_embeddings_dimensions_match
        check (dimensions = extensions.vector_dims(embedding)),
      constraint game_embeddings_document_hash_is_sha256
        check (document_hash ~ '^[0-9a-f]{64}$'),
      constraint game_embeddings_token_count_not_negative check (token_count >= 0)
    );

    alter table public.game_embeddings enable row level security;

    comment on table public.game_embeddings is
      'One vector per game per model (TM11-39). Written by the embedding pipeline.';
    comment on column public.game_embeddings.document_hash is
      'SHA-256 hex of the exact text embedded. Unchanged hash, no re-embed (TM11-41).';
  end if;
end
$$;
