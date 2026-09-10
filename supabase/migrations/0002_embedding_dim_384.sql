-- Switch embeddings from OpenAI (1536-dim) to Hugging Face all-MiniLM-L6-v2
-- (384-dim). Existing vectors are the wrong dimension, so they are cleared and
-- must be regenerated with `python scripts/embed_games.py --all`.
--
-- Idempotent: safe to run whether the column is still 1536 or already 384.

drop index if exists games_embedding_cosine_idx;

-- Clear incompatible vectors first so the type change has only NULLs to convert.
update games set embedding = null where embedding is not null;

alter table games
    alter column embedding type vector(384) using embedding::vector(384);

create index if not exists games_embedding_cosine_idx
    on games using ivfflat (embedding vector_cosine_ops) with (lists = 100);
