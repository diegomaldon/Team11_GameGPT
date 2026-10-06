-- =============================================================================
-- GameGPT :: 20261006120000 :: owned_games.playtime_minutes
-- E4 Platform Linking & Library Sync · REQ010 · TM11-46
-- AC: returns owned appids with playtime for a given Steam ID
-- =============================================================================
--
-- GetOwnedGames hands back `playtime_forever` in minutes for every title. The
-- client (api/services/steam_client.py) now carries it, but the API's write
-- path had nowhere to put it, so it was being read and then dropped.
--
-- ── why `if not exists` rather than a plain `add column` ────────────────────
--
-- There are two `owned_games` definitions in this repo and they do not agree:
--
--   0001_init.sql                  owned_games(id, user_id, game_id, platform,
--                                              steam_appid, title, created_at)
--                                  -- the walking-skeleton table api/db/
--                                  -- repositories.py reads and writes
--
--   20260915120200_create_core_tables.sql
--                                  owned_games(owned_game_id, user_id,
--                                              platform_account_id, game_id,
--                                              playtime_minutes, ...)
--                                  -- the structure-diagram table, and the one
--                                  -- actually present in the hosted project
--
-- So this statement has to be correct in both worlds:
--
--   * Against the hosted database, `playtime_minutes` already exists (it was
--     declared in 20260915120200) and this is a no-op.
--   * Against a database built only from 0001_init.sql — a local dev box, or
--     CI — it adds the column so the Steam sync has somewhere to write.
--
-- Either way the migration is safe to run and safe to re-run.
--
-- ── known debt, deliberately not fixed here ─────────────────────────────────
--
-- Reconciling the two schemas is a real piece of work: the core table requires
-- platform_account_id and game_id NOT NULL, which means library sync would have
-- to resolve (or create) a platform_accounts row and a games row before it can
-- insert anything. That is a story of its own, not a 3-point client ticket.
-- It is not biting today only because DATABASE_URL is unset by default, so
-- Settings.db_enabled is False and repositories.py never runs. See
-- docs/steam-library.md → "Known gap".

alter table if exists public.owned_games
    add column if not exists playtime_minutes integer not null default 0;

comment on column public.owned_games.playtime_minutes is
    'Lifetime playtime in minutes, from Steam GetOwnedGames playtime_forever. 0 means owned but never played.';
