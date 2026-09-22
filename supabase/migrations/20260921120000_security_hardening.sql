-- =============================================================================
-- Team11_GameGPT
-- 20260921120000_security_hardening.sql
--
-- Resolves three Supabase Security Advisor findings:
--
--   1. public.rls_auto_enable() is SECURITY DEFINER and executable by
--      `authenticated` via /rest/v1/rpc/rls_auto_enable
--   2. public.rls_auto_enable() is SECURITY DEFINER and executable by
--      `anon` via the same endpoint
--   3. public.set_updated_at() has a role-mutable search_path
--
-- Runs after 20260915120300_rls_and_grants.sql.
--
-- ON GUARDED STATEMENTS: rls_auto_enable() is created by no migration in this
-- repo -- it exists only on the hosted project, added out of band. A bare
-- ALTER FUNCTION would therefore abort a clean CLI rebuild. Every statement
-- touching it is wrapped in a catalog lookup instead. This is not a return to
-- the re-runnable AC dropped mid-sprint; it is the only way a single file can
-- be correct against both the hosted project and a fresh database.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. A schema PostgREST does not expose
--
-- Anything in `public` is reachable at /rest/v1/. Helper functions that run
-- with elevated rights belong somewhere the Data API cannot see.
--
-- Do NOT add `private` to Exposed schemas under Settings -> API. The default
-- exposure list (public, graphql_public) is correct and should stay as it is.
-- -----------------------------------------------------------------------------

create schema if not exists private;

revoke all on schema private from public;
revoke all on schema private from anon, authenticated;


-- -----------------------------------------------------------------------------
-- 2. Findings 1 and 2 -- public.rls_auto_enable()
--
-- Postgres grants EXECUTE to PUBLIC on every new function by default, and both
-- anon and authenticated inherit PUBLIC. Combined with SECURITY DEFINER, that
-- makes the function callable by an unauthenticated stranger and executed as
-- its owner.
--
-- Order below is deliberate: revoke and pin the search_path while the function
-- still answers to its `public` signature, then move it. If it is wired to an
-- event trigger, the trigger follows the function through the schema change --
-- no recreation needed. Confirm afterwards with:
--     select evtname, evtfoid::regproc from pg_event_trigger;
-- -----------------------------------------------------------------------------

do $$
declare
  fn record;
begin
  for fn in
    select p.oid::regprocedure as sig
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'rls_auto_enable'
  loop
    execute format('revoke all on function %s from public', fn.sig);
    execute format('revoke all on function %s from anon, authenticated', fn.sig);
    execute format('alter function %s set search_path = %L', fn.sig, '');
    execute format('alter function %s set schema private', fn.sig);

    raise notice 'security_hardening: moved % out of public', fn.sig;
  end loop;

  if not found then
    raise notice 'security_hardening: public.rls_auto_enable() absent, nothing to move';
  end if;
end
$$;


-- -----------------------------------------------------------------------------
-- 3. Finding 3 -- public.set_updated_at()
--
-- ALTER rather than CREATE OR REPLACE, so the body defined in
-- 20260915120200_create_core_tables.sql is preserved verbatim. The loop covers
-- any overloads.
--
-- An empty search_path forces every identifier in the body to be
-- schema-qualified. pg_catalog is always searched first whether listed or not,
-- so now() still resolves. If the body references a GameGPT table or enum
-- unqualified, qualify it in the creating migration (public.games,
-- public.platform_type, ...) -- it will not fail here, it will fail at runtime
-- on the next write.
-- -----------------------------------------------------------------------------

do $$
declare
  fn record;
begin
  for fn in
    select p.oid::regprocedure as sig
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'set_updated_at'
  loop
    execute format('alter function %s set search_path = %L', fn.sig, '');

    raise notice 'security_hardening: pinned search_path on %', fn.sig;
  end loop;
end
$$;


-- -----------------------------------------------------------------------------
-- 4. Stop the next function from repeating finding 1
--
-- Default privileges are per-role and apply only to functions created after
-- this point by the role that runs this migration. Functions created by a
-- different role still pick up the PUBLIC grant, so this is a guardrail, not a
-- guarantee.
--
-- Deliberately NOT done: a blanket REVOKE EXECUTE on all existing functions in
-- `public`. pgvector is installed there by 20260915120000_enable_extensions.sql
-- and its operator support functions need EXECUTE. A blanket revoke breaks
-- every embedding query in the RAG pipeline.
-- -----------------------------------------------------------------------------

alter default privileges in schema public
  revoke execute on functions from public;


-- -----------------------------------------------------------------------------
-- 5. Refresh the PostgREST schema cache
-- -----------------------------------------------------------------------------

notify pgrst, 'reload schema';
