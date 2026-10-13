-- =============================================================================
-- GameGPT :: 20261012130000 :: owned_games.import_method
-- TM11-54 Manual title entry library import (REQ004)
-- AC: entries stored with importMethod MANUAL against the right platform
-- =============================================================================
--
-- ImportMethod (OAUTH | MANUAL) only exists on platform_accounts today. The
-- 0001_init.sql owned_games table, the one api/db/repositories.py writes, has
-- no account row to hang it on: each game carries its own `platform`. So the
-- method goes on the game row itself, next to that platform.
--
--   OAUTH   the default, so every existing row and every Steam sync keeps
--           its meaning.
--   MANUAL  added by the user by hand. repositories.add_manual_game sets it.
--
-- Plain text with a check, not the public.import_method enum: a database built
-- only from 0001_init.sql (CI, a dev box) has no enums.
--
-- Duplicates are already blocked by owned_games_user_platform_manual_game_key
-- (20261012120000, TM11-55), which add_manual_game relies on.
--
-- Guarded like 20261012120000: the hosted core shape of owned_games has no
-- `platform` column and gets its method from platform_accounts.import_method,
-- so there this is a no-op. See docs/steam-library.md, Known gap.
-- =============================================================================

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'owned_games' and column_name = 'platform'
  ) then
    alter table public.owned_games
      add column if not exists import_method text not null default 'OAUTH';

    if not exists (
      select 1 from pg_constraint where conname = 'owned_games_import_method_check'
    ) then
      alter table public.owned_games
        add constraint owned_games_import_method_check
        check (import_method in ('OAUTH', 'MANUAL'));
    end if;

    comment on column public.owned_games.import_method is
      'OAUTH: the default, written by platform imports. MANUAL: added by the user by hand.';
  end if;
end
$$;
