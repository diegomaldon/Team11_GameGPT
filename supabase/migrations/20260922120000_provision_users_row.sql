-- =============================================================================
-- GameGPT :: 20260922120000 :: Provision public.users on signup
-- E2 Identity & Account Management · REQ002 · TM11-26
-- AC: first sign-in provisions a users row with authProvider GOOGLE
-- =============================================================================
--
-- public.users (20260915120200) has an auth_provider column and, until now, nothing
-- ever wrote to it. handle_new_user() only populated public.user_profiles, so the table
-- the structure diagram calls User4 has been empty since it was created. Every signup
-- so far — including the email/password ones from REQ001 — is missing its row.
--
-- This migration extends the existing trigger function rather than adding a second
-- trigger. Both inserts then run in the same transaction as the auth.users insert, so a
-- signup either produces both rows or no account at all. Two triggers could half-succeed.
--
-- Idempotent: safe to re-run.

-- ── provider detection ──────────────────────────────────────────────────────
-- GoTrue records which provider created the account in raw_app_meta_data.provider:
-- 'email' for password signups, 'google' for the OAuth flow. That field is set by
-- GoTrue itself, not by the client — unlike raw_user_meta_data, which is whatever the
-- caller passed to signUp() and is therefore attacker-controlled. Reading the provider
-- from app_meta_data is the difference between a trustworthy value and a forgeable one.
create or replace function public.auth_provider_of(raw_app_meta_data jsonb)
returns public.auth_provider
language sql
immutable
as $$
  select case lower(coalesce(raw_app_meta_data ->> 'provider', 'email'))
           when 'google' then 'GOOGLE'::public.auth_provider
           else 'EMAIL'::public.auth_provider
         end;
$$;

comment on function public.auth_provider_of(jsonb) is
  'Maps GoTrue raw_app_meta_data.provider to the auth_provider enum. Unknown providers fall back to EMAIL.';

-- ── profile creation ────────────────────────────────────────────────────────
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    -- Unchanged from 20260914120000. See that migration for why the display name is
    -- truncated rather than rejected.
    insert into public.user_profiles (id, display_name)
    values (
        new.id,
        left(nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''), 40)
    )
    on conflict (id) do nothing;

    -- New: the User4 row. 'full_name' and 'name' are what Google puts in the OAuth
    -- profile; 'display_name' is what our own registration form sends. Checking all
    -- three means a Google user gets a real name instead of a null.
    insert into public.users (user_id, email, display_name, auth_provider)
    values (
        new.id,
        new.email,
        left(
            nullif(
                trim(coalesce(
                    new.raw_user_meta_data ->> 'display_name',
                    new.raw_user_meta_data ->> 'full_name',
                    new.raw_user_meta_data ->> 'name'
                )),
                ''
            ),
            40
        ),
        public.auth_provider_of(new.raw_app_meta_data)
    )
    -- Untargeted on purpose, so it swallows the users_email_key collision as well as the
    -- primary key one. That index is on lower(email) and can only fire when a *different*
    -- auth.users row already holds the address — which GoTrue normally prevents by
    -- linking verified emails to the existing account instead of creating a second one.
    -- If it ever does fire, skipping the row leaves an account with no User4 row, which
    -- is visible and repairable. Raising instead would abort the signup and lock the
    -- person out entirely. See docs/auth-google-oauth.md.
    on conflict do nothing;

    return new;
end;
$$;

-- Trigger definition is unchanged; recreated so this migration stands alone.
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
    after insert on auth.users
    for each row
    execute function public.handle_new_user();

-- ── backfill ────────────────────────────────────────────────────────────────
-- Accounts created before this migration have no users row. Without this they would stay
-- invisible to every join in the app. auth_provider is recovered from the same metadata
-- the trigger reads, so a backfilled row is indistinguishable from a freshly created one.
insert into public.users (user_id, email, display_name, auth_provider, created_at)
select
    au.id,
    au.email,
    left(
        nullif(
            trim(coalesce(
                au.raw_user_meta_data ->> 'display_name',
                au.raw_user_meta_data ->> 'full_name',
                au.raw_user_meta_data ->> 'name'
            )),
            ''
        ),
        40
    ),
    public.auth_provider_of(au.raw_app_meta_data),
    au.created_at
from auth.users au
where au.email is not null
on conflict do nothing;

-- ── what this deliberately does NOT do ──────────────────────────────────────
-- auth_provider records how the account was FIRST created and is never updated
-- afterwards. When someone who registered with a password later signs in with Google,
-- GoTrue links the new identity to the existing auth.users row — no INSERT happens, this
-- trigger does not fire, and the row correctly still says EMAIL.
--
-- Do not "fix" that by flipping the column on link. It would turn a stable fact about
-- account origin into a race between whichever provider was used most recently, and
-- nothing in the app wants that. Identity linking is tracked in auth.identities, which is
-- the right place to ask "can this person use Google?".
