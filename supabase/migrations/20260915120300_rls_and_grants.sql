-- =============================================================================
-- GameGPT :: 20260915120300 :: Row Level Security + Data API grants
-- =============================================================================
-- READ THIS BEFORE DELETING ANY OF IT:
--
-- Supabase changed a default on 2026-05-30. New projects no longer auto-expose
-- public-schema tables to the Data API -- the REST/GraphQL layer that
-- supabase-js calls. Existing projects get the same treatment on 2026-10-30.
-- Without the explicit GRANTs at the bottom of this file, every supabase-js
-- query against these tables fails with a permission error, even though the
-- tables exist and look fine in the Table Editor.
--
-- GRANT and RLS are two different gates. GRANT decides whether a role can touch
-- the table at all; RLS decides which rows it sees. Both are required.
-- =============================================================================

alter table public.users                   enable row level security;
alter table public.platform_accounts       enable row level security;
alter table public.games                   enable row level security;
alter table public.owned_games             enable row level security;
alter table public.queries                 enable row level security;
alter table public.recommendations         enable row level security;
alter table public.recommendation_feedback enable row level security;

-- ---------- users ----------
create policy users_select_own on public.users
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy users_insert_own on public.users
  for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy users_update_own on public.users
  for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy users_delete_own on public.users
  for delete to authenticated
  using ((select auth.uid()) = user_id);

-- ---------- platform_accounts ----------
create policy platform_accounts_own on public.platform_accounts
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

-- ---------- games ----------
-- Shared catalogue: anyone signed in can read it, nobody writes it from the
-- client. The metadata importer writes with the service role, which bypasses
-- RLS entirely.
create policy games_read_all on public.games
  for select to authenticated
  using (true);

-- ---------- owned_games ----------
create policy owned_games_own on public.owned_games
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

-- ---------- queries ----------
create policy queries_own on public.queries
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

-- ---------- recommendations ----------
-- No user_id column; ownership is inherited through the parent query.
create policy recommendations_select_own on public.recommendations
  for select to authenticated
  using (
    exists (
      select 1 from public.queries q
      where q.query_id = recommendations.query_id
        and q.user_id = (select auth.uid())
    )
  );

-- ---------- recommendation_feedback ----------
create policy recommendation_feedback_own on public.recommendation_feedback
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

-- =============================================================================
-- Data API grants
-- =============================================================================
grant usage on schema public to anon, authenticated, service_role;

grant select, insert, update, delete on public.users                   to authenticated;
grant select, insert, update, delete on public.platform_accounts       to authenticated;
grant select, insert, update, delete on public.owned_games             to authenticated;
grant select, insert, update, delete on public.queries                 to authenticated;
grant select                         on public.recommendations         to authenticated;
grant select, insert, update, delete on public.recommendation_feedback to authenticated;
grant select                         on public.games                   to authenticated;

-- Server-side ingestion and the recommendation writer.
grant select, insert, update, delete on all tables in schema public to service_role;

-- anon gets nothing. Add a grant here only if a table must be readable while
-- logged out, and pair it with a matching RLS policy for the anon role.
