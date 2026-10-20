-- =============================================================================
-- GameGPT :: 20261020120000 :: game_embeddings_template_version
-- TM11-38 Compose per-game embedding documents (REQ011)
-- AC: template versioned so re-embedding is traceable
-- =============================================================================
--
-- Records which document template (api/services/game_document.py,
-- docs/embedding-documents.md) produced the text behind each vector.
--
-- Rows already here were embedded by TM11-39's "title description genres"
-- text, so they are backfilled as 'v0'. The pipeline treats a row from an
-- older template as changed and re-embeds it on its next run.
--
-- No default after the backfill: the pipeline always writes the version, so a
-- row that leaves it out is a bug and should fail.
--
-- Guarded like 20261017120000: game_embeddings only exists on the hosted shape.
-- =============================================================================

do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'public' and table_name = 'game_embeddings'
  ) then
    alter table public.game_embeddings
      add column if not exists template_version text not null default 'v0';

    alter table public.game_embeddings
      alter column template_version drop default;

    if not exists (
      select 1 from pg_constraint
      where conname = 'game_embeddings_template_version_format'
    ) then
      alter table public.game_embeddings
        add constraint game_embeddings_template_version_format
        check (template_version ~ '^v[0-9]+$');
    end if;

    comment on column public.game_embeddings.template_version is
      'Document template the embedded text was built with (TM11-38). Older than the pipeline''s, re-embed.';
  end if;
end
$$;
