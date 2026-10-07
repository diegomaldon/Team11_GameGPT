-- =============================================================================
-- GameGPT :: 20261006130000 :: owned_games.imported_at + platform_account_id
-- E4 Platform Linking & Library Sync · UC05 · TM11-XX "Idempotent owned_games upsert"
-- AC-01: owned_games rows written with playtimeMinutes and importedAt
-- AC-03: rows attributed to the correct platform_account
-- =============================================================================
--
-- This is the story TM11-46 deferred. Its migration
-- (20261006120000_owned_games_playtime.sql) added `playtime_minutes` and said
-- so explicitly:
--
--     "Reconciling the two schemas is a real piece of work: the core table
--      requires platform_account_id and game_id NOT NULL ... That is a story of
--      its own, not a 3-point client ticket."
--
-- This migration does the owned_games half of that reconciliation: the two
-- columns OwnedGame4 specifies that nothing in the repo has ever written.
--
-- ── the two schemas, again ──────────────────────────────────────────────────
--
--   0001_init.sql                         owned_games(id, user_id, game_id,
--                                                     platform, steam_appid,
--                                                     title, created_at)
--                                         -- what api/db/repositories.py reads
--                                            and writes; local dev box and CI
--
--   20260915120200_create_core_tables.sql owned_games(owned_game_id, user_id,
--                                                     platform_account_id,
--                                                     game_id, playtime_minutes,
--                                                     imported_at, ...)
--                                         -- the structure-diagram table, and
--                                            the one in the hosted project
--
-- Every statement below is written to be correct in both worlds:
--
--   * Hosted project — `imported_at` and `platform_account_id` were declared in
--     20260915120200, so the add-column blocks are no-ops. The backfill still
--     runs and still does useful work.
--   * Dev box / CI built from 0001_init.sql — both columns are added, pointed
--     at that schema's `platform_accounts(id)` primary key.
--
-- The PK column of platform_accounts differs between the two (`id` vs
-- `platform_account_id`), which is why the FK is resolved at runtime from
-- the catalog rather than hardcoded.
--
-- Idempotent. Safe to run, and safe to re-run, against either schema.

-- ── imported_at ─────────────────────────────────────────────────────────────
-- AC-01. `created_at` already exists on the 0001_init table, but it means
-- something different: when the row first appeared. `imported_at` is when the
-- most recent sync last touched it, so it moves on every re-import. Keeping
-- both is the point — "owned since" and "last seen in a sync" are different
-- questions, and UC05 needs the second one.
alter table if exists public.owned_games
    add column if not exists imported_at timestamptz not null default now();

comment on column public.owned_games.imported_at is
    'When the most recent library sync last wrote this row. Moves on every '
    're-import; see created_at for when the row first appeared.';

-- ── platform_account_id ─────────────────────────────────────────────────────
-- AC-03. Nullable on purpose. The core table declares it NOT NULL, but on the
-- skeleton table there are already rows (supabase/seed.sql) with no account to
-- point at, and a NOT NULL add-column against a populated table would fail.
-- The backfill below closes as much of that gap as can be closed unambiguously;
-- the rest is enforced in the write path, which always supplies an id.
do $$
declare
    pa_pk text;
begin
    if to_regclass('public.owned_games') is null then
        return;
    end if;

    if exists (
        select 1 from information_schema.columns
         where table_schema = 'public'
           and table_name   = 'owned_games'
           and column_name  = 'platform_account_id'
    ) then
        return;  -- hosted project: already declared in 20260915120200
    end if;

    -- Which primary key does platform_accounts use in THIS database?
    select a.attname into pa_pk
      from pg_index i
      join pg_attribute a
        on a.attrelid = i.indrelid and a.attnum = any(i.indkey)
     where i.indrelid = 'public.platform_accounts'::regclass
       and i.indisprimary;

    if pa_pk is null then
        raise exception
            'platform_accounts has no primary key; cannot add owned_games.platform_account_id';
    end if;

    execute format(
        'alter table public.owned_games
             add column platform_account_id uuid
             references public.platform_accounts(%I) on delete cascade',
        pa_pk
    );
end
$$;

comment on column public.owned_games.platform_account_id is
    'The linked platform account this row was imported from. Null only on rows '
    'that predate attribution; the sync write path always supplies it.';

create index if not exists owned_games_platform_account_idx
    on public.owned_games (platform_account_id);

-- ── backfill ────────────────────────────────────────────────────────────────
-- Attach existing orphan rows to an account where the answer is unambiguous:
-- the user has exactly one linked account on that platform. Where a user has
-- two Steam accounts linked, which library a pre-attribution row came from is
-- genuinely unknown, so those rows are left null rather than guessed at. The
-- next sync attributes them correctly (see attach_orphan_owned_games in
-- api/db/repositories.py).
--
-- Guarded by a column check so it is a no-op on a database where owned_games
-- carries no `platform` column.
do $$
begin
    if not exists (
        select 1 from information_schema.columns
         where table_schema = 'public'
           and table_name   = 'owned_games'
           and column_name  = 'platform'
    ) then
        return;
    end if;

    execute $sql$
        update public.owned_games og
           set platform_account_id = pa.id
          from public.platform_accounts pa
         where og.platform_account_id is null
           and pa.user_id  = og.user_id
           and pa.platform = og.platform
           and (
               select count(*) from public.platform_accounts p2
                where p2.user_id  = og.user_id
                  and p2.platform = og.platform
           ) = 1
    $sql$;
exception
    when undefined_column then
        -- Hosted schema: platform_accounts.id is named platform_account_id and
        -- owned_games.platform_account_id is already populated by the write
        -- path. Nothing to backfill.
        null;
end
$$;
