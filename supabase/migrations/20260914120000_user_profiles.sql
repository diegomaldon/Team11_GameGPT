-- GameGPT · E2 Identity & Account Management · REQ001
--
-- public.user_profiles — the application-side row that hangs off a real Supabase auth
-- account. Created by a trigger on auth.users, never by client code.
--
-- Why a trigger and not an insert from the browser (AC4):
--   A client-side insert after signUp is a second network call that can fail on its own.
--   If it does — or if email confirmation is on, so there is no session yet and RLS
--   rejects the write — you end up with an auth.users row and no profile. The user can
--   then sign in to an app that cannot join anything against them, and nothing in the
--   client is able to repair it. A trigger runs inside the same transaction as the signup,
--   so the profile either exists or the account was never created.
--
-- Naming: user_profiles, not users. public.users already exists in this database (the
-- walking-skeleton table from 0001_init.sql) and auth.users is Supabase's own. A third
-- table called "users" would be actively dangerous.
--
-- Every identifier below is schema-qualified on purpose. Bare `users` in a Supabase
-- database is ambiguous between public.users and auth.users, and resolves differently
-- depending on search_path.
--
-- Idempotent: safe to re-run against a database that already has it.

-- ── table ───────────────────────────────────────────────────────────────────
create table if not exists public.user_profiles (
    id           uuid primary key references auth.users (id) on delete cascade,

    -- Nullable: display name is optional at registration (registerSchema marks it
    -- .optional()). The length cap mirrors the client's 40-character limit, but it is a
    -- backstop rather than the real guard — see handle_new_user() below.
    display_name text check (char_length(display_name) <= 40),

    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

comment on table public.user_profiles is
    'Profile row for a Supabase auth account. Written only by handle_new_user(); no client INSERT policy exists.';

-- ── profile creation ────────────────────────────────────────────────────────
-- SECURITY DEFINER so the function runs as its owner and bypasses RLS. That is the whole
-- mechanism: the trigger can insert, and no client role can, because no INSERT policy
-- exists further down.
--
-- `set search_path` is not decoration. Without it a SECURITY DEFINER function resolves
-- unqualified names using the *caller's* search_path, which is a well-known privilege
-- escalation path.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    insert into public.user_profiles (id, display_name)
    values (
        new.id,
        -- raw_user_meta_data is whatever the caller passed to signUp(), so it is
        -- attacker-controlled: anyone can hit the Supabase API directly and skip the
        -- form's validation entirely. Truncate rather than reject — raising here would
        -- abort the enclosing transaction and fail the whole signup over a long nickname.
        left(nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''), 40)
    )
    on conflict (id) do nothing;

    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row
    execute function public.handle_new_user();

-- ── updated_at maintenance ──────────────────────────────────────────────────
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists user_profiles_touch_updated_at on public.user_profiles;
create trigger user_profiles_touch_updated_at
    before update on public.user_profiles
    for each row
    execute function public.touch_updated_at();

-- ── row level security ──────────────────────────────────────────────────────
-- With RLS enabled and no policy for a given command, that command is denied. So the
-- absence of an INSERT policy below is the enforcement, not an oversight.
alter table public.user_profiles enable row level security;

drop policy if exists user_profiles_select_own on public.user_profiles;
create policy user_profiles_select_own
    on public.user_profiles
    for select
    to authenticated
    -- Wrapped in a subselect so the planner evaluates auth.uid() once per statement
    -- rather than once per row.
    using ((select auth.uid()) = id);

drop policy if exists user_profiles_update_own on public.user_profiles;
create policy user_profiles_update_own
    on public.user_profiles
    for update
    to authenticated
    using ((select auth.uid()) = id)
    with check ((select auth.uid()) = id);

-- DELIBERATELY ABSENT (AC4): no INSERT policy and no DELETE policy.
--
--   INSERT — the trigger is the only writer. A client-side insert is precisely the bug
--            this design exists to prevent, and register.test.ts asserts signUp is called
--            exactly once to catch anyone reintroducing it.
--   DELETE — account deletion cascades from auth.users. A profile row should never
--            outlive its account, nor be removable while the account exists.
--
-- Do not add either without revisiting AC4.

-- Belt and braces: RLS already denies these, but revoking the grants means a future
-- migration that enables RLS incorrectly still cannot open a write path by accident.
revoke insert, delete on public.user_profiles from anon, authenticated;
grant select, update on public.user_profiles to authenticated;
