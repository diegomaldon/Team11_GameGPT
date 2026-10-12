-- =============================================================================
-- GameGPT :: 20261012120000 :: One row per hand-imported game
-- TM11-55 CSV library upload with match review (REQ004)
-- =============================================================================
-- owned_games is de-duplicated on (user_id, platform, steam_appid). Games
-- imported from a CSV for Epic or Xbox have no steam_appid, and Postgres never
-- treats two NULLs as equal, so uploading the same file twice would add every
-- game twice.
--
-- This index closes that gap for rows without a steam_appid only. Steam sync
-- rows are left alone on purpose: two Steam editions (DOOM and DOOM Deluxe)
-- can match the same games row, and that must keep working.
-- repositories.add_owned_games inserts with `on conflict do nothing`, so a
-- duplicate is skipped, never an error.
--
-- Guarded like 20261006120000: the repo has two owned_games shapes (see
-- docs/steam-library.md, Known gap). Only the 0001_init.sql shape has
-- platform/steam_appid columns; the hosted core shape already has
-- unique (platform_account_id, game_id), so there this is a no-op.
-- =============================================================================

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'owned_games' and column_name = 'platform'
  ) and exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'owned_games' and column_name = 'steam_appid'
  ) then
    create unique index if not exists owned_games_user_platform_manual_game_key
      on public.owned_games (user_id, platform, game_id)
      where steam_appid is null and game_id is not null;
  end if;
end
$$;
