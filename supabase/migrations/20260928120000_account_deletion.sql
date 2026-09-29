-- =============================================================================
-- GameGPT :: 20260928120000 :: Account deletion
-- E2 Identity & Account Management · REQ005 · TM11-xx
-- AC: removes user, platform accounts, owned games, queries, recommendations
--     and feedback
-- AC: verified by querying every table for the deleted user id
-- =============================================================================
--
-- The cascade already exists. Every user-bearing table was declared with
-- `on delete cascade` back in 20260915120200, and both public.users and
-- public.user_profiles hang off auth.users the same way:
--
--   auth.users
--     ├── public.user_profiles            (id)
--     └── public.users                    (user_id)
--           ├── public.platform_accounts  (user_id)
--           │     └── public.owned_games  (platform_account_id)
--           ├── public.owned_games        (user_id)
--           ├── public.queries            (user_id)
--           │     └── public.recommendations          (query_id)
--           │           └── public.recommendation_feedback (recommendation_id)
--           └── public.recommendation_feedback        (user_id)
--
-- So deleting one row from auth.users removes everything. What was missing is a
-- way for a signed-in user to trigger that. The anon key cannot touch auth.users,
-- and handing the service-role key to the browser to fix that would be far worse
-- than the problem — it bypasses RLS entirely for every table.
--
-- Hence a SECURITY DEFINER function that deletes exactly one row, chosen by
-- auth.uid() rather than by any argument the caller controls.
--
-- Idempotent: safe to re-run.

-- ── deletion ────────────────────────────────────────────────────────────────
-- Takes no arguments, deliberately. A delete_account(uuid) signature would be
-- one missing authorization check away from letting any signed-in user delete
-- anyone else's account, and SECURITY DEFINER means it would succeed. The only
-- id this function will ever act on is the caller's own.
create or replace function public.delete_my_account()
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  caller uuid := auth.uid();
begin
  -- Belt and braces. RLS is not what protects this function — SECURITY DEFINER
  -- runs as the owner — so the guard has to be here. A null uid means no JWT,
  -- and `delete ... where id is null` would quietly delete nothing and report
  -- success, which is the worst possible outcome for a destructive call.
  if caller is null then
    raise exception 'delete_my_account: no authenticated user'
      using errcode = '28000';
  end if;

  -- One statement. Every table listed in the diagram above goes with it.
  delete from auth.users where id = caller;
end;
$$;

comment on function public.delete_my_account() is
  'REQ005. Deletes the calling user''s auth.users row; FK cascades remove all application data. Acts only on auth.uid().';

-- 20260921120000 revoked EXECUTE from PUBLIC by default for functions created
-- in this schema, so this grant is required rather than decorative. Without it
-- the call fails as "function does not exist" from PostgREST, which is a
-- confusing way to learn about default privileges.
revoke all on function public.delete_my_account() from public;
grant execute on function public.delete_my_account() to authenticated;

-- ── verification ────────────────────────────────────────────────────────────
-- AC: "verified by querying every table for the deleted user id".
--
-- Run this before and after a deletion with the same uuid. Before, it shows
-- where that user's data lives; after, every row_count must be 0. Checking the
-- tables by hand invites forgetting one, which is exactly the failure this is
-- meant to catch.
--
-- SECURITY INVOKER (the default) on purpose: it runs with the caller's rights,
-- so RLS still applies and no grant is added below. Run it from the SQL editor
-- or as the service role. A function that returned per-user row counts for an
-- arbitrary uuid to any signed-in user would be a quiet enumeration oracle.
create or replace function public.account_data_footprint(target uuid)
returns table (table_name text, row_count bigint)
language sql
stable
set search_path = public, pg_temp
as $$
  select 'auth.users',                     count(*) from auth.users                     where id = target
  union all
  select 'public.users',                   count(*) from public.users                   where user_id = target
  union all
  select 'public.user_profiles',           count(*) from public.user_profiles           where id = target
  union all
  select 'public.platform_accounts',       count(*) from public.platform_accounts       where user_id = target
  union all
  select 'public.owned_games',             count(*) from public.owned_games             where user_id = target
  union all
  select 'public.queries',                 count(*) from public.queries                 where user_id = target
  union all
  -- recommendations hang off queries, not off the user, so they need the join.
  -- Counting them by user_id would not compile and, worse, leaving them out
  -- would let orphaned rows pass the check.
  select 'public.recommendations',         count(*)
    from public.recommendations r
    join public.queries q on q.query_id = r.query_id
   where q.user_id = target
  union all
  select 'public.recommendation_feedback', count(*) from public.recommendation_feedback where user_id = target
  order by 1;
$$;

comment on function public.account_data_footprint(uuid) is
  'REQ005 verification. Row counts per table for one user id; all zero after deletion.';
