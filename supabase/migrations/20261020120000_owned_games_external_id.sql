-- =============================================================================
-- GameGPT :: 20261020120000 :: owned_games.external_id
-- TM11-56 Xbox library import (REQ014)
-- AC: idempotent on re-run
-- =============================================================================
--
-- Steam rows are de-duplicated on (user_id, platform, steam_appid). Xbox titles
-- have no steam_appid, and the TM11-55 index (user_id, platform, game_id) only
-- covers titles that matched a games row. An unmatched Xbox title has neither,
-- so without a key of its own every re-import would add it again.
--
--   external_id  the storefront's own id for the title: the Xbox titleId for
--                platform 'xbox'. NULL for Steam, CSV and manual rows, which
--                keep their existing keys.
--
-- The partial unique index makes (user_id, platform, external_id) the upsert
-- target for api/db/repositories.apply_xbox_import.
--
-- Guarded like 20261012120000: only the 0001_init.sql shape of owned_games has
-- a `platform` column. The hosted core shape is a no-op here. See
-- docs/steam-library.md, Known gap.
-- =============================================================================

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'owned_games' and column_name = 'platform'
  ) then
    alter table public.owned_games
      add column if not exists external_id text;

    create unique index if not exists owned_games_user_platform_external_id_key
      on public.owned_games (user_id, platform, external_id)
      where external_id is not null;

    comment on column public.owned_games.external_id is
      'Storefront id for the title (Xbox titleId). NULL for Steam, CSV and manual rows.';
  end if;
end
$$;
