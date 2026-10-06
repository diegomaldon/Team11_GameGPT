-- =============================================================================
-- GameGPT :: 20261004120000 :: Library import title matching
-- Match imported titles to games rows
-- AC: exact and normalised matching against games
-- AC: unmatched titles recorded for review rather than dropped silently
-- AC: match rate reported per import
-- =============================================================================
-- Matching itself happens in api/services/title_matching.py. These tables keep
-- its output:
--
--   library_imports           one row per import run, with counts per match
--                             tier and the match rate
--   unmatched_import_titles   the review queue: every title that did not
--                             resolve to a games row, with the reason
--
-- Unmatched rows are keyed on (user_id, platform, source_title), so a re-import
-- refreshes last_import_id/last_seen_at instead of piling up duplicates, and a
-- title already resolved by a reviewer stays resolved.
-- =============================================================================

create table public.library_imports (
  import_id          uuid primary key default extensions.gen_random_uuid(),
  user_id            uuid not null references public.users (user_id) on delete cascade,
  platform           public.platform_type not null,
  source             text not null,                 -- 'steam' | 'seed' | ...
  total_titles       integer not null default 0 check (total_titles >= 0),
  matched_appid      integer not null default 0 check (matched_appid >= 0),
  matched_exact      integer not null default 0 check (matched_exact >= 0),
  matched_normalised integer not null default 0 check (matched_normalised >= 0),
  matched_edition    integer not null default 0 check (matched_edition >= 0),
  unmatched          integer not null default 0 check (unmatched >= 0),
  -- matched / total, 0..1. Stored rather than derived so reporting is a plain
  -- select and the value is exactly what the API returned for that run.
  match_rate         numeric(5,4) not null default 0 check (match_rate between 0 and 1),
  imported_at        timestamptz not null default now(),
  constraint library_imports_totals_add_up check (
    matched_appid + matched_exact + matched_normalised + matched_edition + unmatched
      = total_titles
  )
);

create index library_imports_user_imported_at_idx
  on public.library_imports (user_id, imported_at desc);

comment on table public.library_imports is
  'One row per library import with title-match counts and match rate.';

create table public.unmatched_import_titles (
  unmatched_id       uuid primary key default extensions.gen_random_uuid(),
  user_id            uuid not null references public.users (user_id) on delete cascade,
  platform           public.platform_type not null,
  source_title       text not null,                 -- exactly as the storefront sent it
  external_id        text,                          -- e.g. steam appid, when known
  normalised_title   text not null,
  reason             text not null check (reason in ('no_match', 'ambiguous', 'blank_title')),
  candidate_game_ids uuid[] not null default '{}',  -- filled when reason = 'ambiguous'
  status             text not null default 'pending'
                       check (status in ('pending', 'resolved', 'ignored')),
  resolved_game_id   uuid references public.games (game_id) on delete set null,
  first_import_id    uuid references public.library_imports (import_id) on delete set null,
  last_import_id     uuid references public.library_imports (import_id) on delete set null,
  first_seen_at      timestamptz not null default now(),
  last_seen_at       timestamptz not null default now(),
  constraint unmatched_import_titles_user_platform_title_key
    unique (user_id, platform, source_title),
  constraint unmatched_import_titles_resolved_has_game check (
    status <> 'resolved' or resolved_game_id is not null
  )
);

create index unmatched_import_titles_status_idx
  on public.unmatched_import_titles (status, last_seen_at desc);
create index unmatched_import_titles_normalised_idx
  on public.unmatched_import_titles (normalised_title);

comment on table public.unmatched_import_titles is
  'Review queue of imported titles that did not resolve to a games row.';

-- ---------- RLS + grants ----------
-- Users can read their own import history and review queue. Writes come from
-- the API with the service role, which bypasses RLS.
alter table public.library_imports         enable row level security;
alter table public.unmatched_import_titles enable row level security;

create policy library_imports_select_own on public.library_imports
  for select to authenticated
  using ((select auth.uid()) = user_id);

create policy unmatched_import_titles_select_own on public.unmatched_import_titles
  for select to authenticated
  using ((select auth.uid()) = user_id);

grant select on public.library_imports         to authenticated;
grant select on public.unmatched_import_titles to authenticated;
grant select, insert, update, delete on public.library_imports         to service_role;
grant select, insert, update, delete on public.unmatched_import_titles to service_role;
