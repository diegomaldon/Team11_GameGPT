-- =============================================================================
-- GameGPT :: 20260915120200 :: Core tables
-- Source: CIS453 structure diagram section 3
-- AC: users, platform_accounts, owned_games, games, queries,
--     recommendations, recommendation_feedback
-- =============================================================================
-- Table order follows the FK dependency graph from the diagram's block
-- relationships:
--   users -> platform_accounts -> games -> owned_games
--   users -> queries -> recommendations -> recommendation_feedback
-- =============================================================================

-- -----------------------------------------------------------------------------
-- users  (3.21 User4)
-- -----------------------------------------------------------------------------
-- DEVIATION FROM DIAGRAM: User4.passwordHash is intentionally omitted.
-- REQ001 puts auth under Supabase, which stores the hash in
-- auth.users.encrypted_password. A second copy of a credential we do not
-- control is a liability, so public.users is a profile table keyed 1:1 to
-- auth.users instead.
-- -----------------------------------------------------------------------------
create table public.users (
  user_id       uuid primary key references auth.users (id) on delete cascade,
  email         text not null,
  display_name  text,
  auth_provider public.auth_provider not null default 'EMAIL',
  created_at    timestamptz not null default now()
);

create unique index users_email_key on public.users (lower(email));

comment on table public.users is
  'Profile row per authenticated user, 1:1 with auth.users. Structure diagram 3.21 User4.';

-- -----------------------------------------------------------------------------
-- platform_accounts  (3.11 PlatformAccount4)
-- Relationship: User4 -> PlatformAccount4
-- -----------------------------------------------------------------------------
create table public.platform_accounts (
  platform_account_id uuid primary key default extensions.gen_random_uuid(),
  user_id             uuid not null references public.users (user_id) on delete cascade,
  platform            public.platform_type not null,
  platform_user_id    text not null,
  access_token        text,
  import_method       public.import_method not null default 'OAUTH',
  linked_at           timestamptz not null default now(),
  last_synced_at      timestamptz,
  constraint platform_accounts_user_platform_key
    unique (user_id, platform),
  constraint platform_accounts_platform_identity_key
    unique (platform, platform_user_id)
);

create index platform_accounts_user_id_idx on public.platform_accounts (user_id);

comment on column public.platform_accounts.access_token is
  'SECURITY DEBT: plaintext today. Move to Supabase Vault before any real OAuth token is stored (Secure Data Handling use case).';

-- -----------------------------------------------------------------------------
-- games  (3.6 Game4)
-- -----------------------------------------------------------------------------
-- ADDITIONS BEYOND THE DIAGRAM:
--   steam_appid / igdb_id / rawg_id  -- upsert keys for the metadata ingestion
--                                       ticket. Without these, re-running the
--                                       importer duplicates every row.
--   release_date / developers / publishers / header_image_url
--                                    -- REQ009 and use case 2.20 promise
--                                       developer and release date in the game
--                                       detail panel, but Game4 has no
--                                       properties for them. Raised as a gap.
-- -----------------------------------------------------------------------------
create table public.games (
  game_id             uuid primary key default extensions.gen_random_uuid(),
  title               text not null,
  description         text,
  genres              text[] not null default '{}',
  tags                text[] not null default '{}',
  available_platforms public.platform_type[] not null default '{}',
  purchase_links      jsonb not null default '{}'::jsonb,
  critic_score        smallint check (critic_score between 0 and 100),
  review_score        smallint check (review_score between 0 and 100),
  embedding           extensions.vector(1536),

  -- external source identifiers
  steam_appid         integer,
  igdb_id             integer,
  rawg_id             integer,

  -- detail-panel fields (REQ009)
  release_date        date,
  developers          text[] not null default '{}',
  publishers          text[] not null default '{}',
  header_image_url    text,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint games_steam_appid_key unique (steam_appid),
  constraint games_igdb_id_key     unique (igdb_id),
  constraint games_rawg_id_key     unique (rawg_id),
  constraint games_title_not_blank check (length(btrim(title)) > 0)
);

create index games_genres_idx              on public.games using gin (genres);
create index games_tags_idx                on public.games using gin (tags);
create index games_available_platforms_idx on public.games using gin (available_platforms);
create index games_title_trgm_idx          on public.games using gin (title extensions.gin_trgm_ops);

-- Vector index for the RAG pipeline (3.14, 3.22). Cosine distance, matching the
-- usual normalized-embedding setup. Safe to build on an empty table.
create index games_embedding_idx
  on public.games using hnsw (embedding extensions.vector_cosine_ops);

comment on column public.games.available_platforms is
  'Storefronts that carry the title (REQ008) -- NOT operating systems. Steam appdetails returns windows/mac/linux; that is a different concept and must not be mapped here.';
comment on column public.games.purchase_links is
  'jsonb keyed by platform_type, e.g. {"STEAM": "https://store.steampowered.com/app/440"} (REQ012).';
comment on column public.games.embedding is
  'Dimension 1536 assumes OpenAI text-embedding-3-small. Change here and in queries.embedding_vector together if the model changes.';

-- keep updated_at honest
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger games_set_updated_at
  before update on public.games
  for each row execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- owned_games  (3.10 OwnedGame4)
-- Relationships: User4 -> OwnedGame4, Game4 -> OwnedGame4,
--                OwnedGame4 -> PlatformAccount4
-- -----------------------------------------------------------------------------
create table public.owned_games (
  owned_game_id        uuid primary key default extensions.gen_random_uuid(),
  user_id              uuid not null references public.users (user_id) on delete cascade,
  platform_account_id  uuid not null references public.platform_accounts (platform_account_id) on delete cascade,
  game_id              uuid not null references public.games (game_id) on delete cascade,
  playtime_minutes     integer not null default 0 check (playtime_minutes >= 0),
  achievement_progress numeric(5,2) check (achievement_progress between 0 and 100),
  imported_at          timestamptz not null default now(),
  -- makes library re-sync (UC05 Refresh Linked Libraries) an idempotent upsert
  constraint owned_games_account_game_key unique (platform_account_id, game_id)
);

create index owned_games_user_id_idx on public.owned_games (user_id);
create index owned_games_game_id_idx on public.owned_games (game_id);
-- supports REQ007 ownership filtering: "does this user own this game anywhere"
create index owned_games_user_game_idx on public.owned_games (user_id, game_id);

-- -----------------------------------------------------------------------------
-- queries  (3.13 Query4)
-- Relationship: User4 -> Query4
-- -----------------------------------------------------------------------------
-- DEVIATION: Query4.timestamp is named created_at here. "timestamp" is a
-- Postgres type name; using it as a column identifier forces quoting in every
-- ORM and hand-written query downstream.
-- -----------------------------------------------------------------------------
create table public.queries (
  query_id         uuid primary key default extensions.gen_random_uuid(),
  user_id          uuid not null references public.users (user_id) on delete cascade,
  query_text       text not null check (length(btrim(query_text)) > 0),
  embedding_vector extensions.vector(1536),
  created_at       timestamptz not null default now()
);

-- REQ037: query history on the profile dashboard, newest first
create index queries_user_created_at_idx on public.queries (user_id, created_at desc);

-- -----------------------------------------------------------------------------
-- recommendations  (3.15 Recommendation4)
-- Relationships: Query4 -> Recommendation4, Recommendation4 -> Game4
-- -----------------------------------------------------------------------------
create table public.recommendations (
  recommendation_id uuid primary key default extensions.gen_random_uuid(),
  query_id          uuid not null references public.queries (query_id) on delete cascade,
  game_id           uuid not null references public.games (game_id) on delete cascade,
  rank              smallint not null check (rank between 1 and 5),  -- REQ015: 3-5 results
  explanation       text,
  generated_at      timestamptz not null default now(),
  constraint recommendations_query_rank_key unique (query_id, rank),
  constraint recommendations_query_game_key unique (query_id, game_id)
);

create index recommendations_query_id_idx on public.recommendations (query_id);
create index recommendations_game_id_idx  on public.recommendations (game_id);

-- -----------------------------------------------------------------------------
-- recommendation_feedback  (3.16 RecommendationFeedback4)
-- Relationships: Recommendation4 -> RecommendationFeedback4,
--                RecommendationFeedback4 -> User4
-- -----------------------------------------------------------------------------
create table public.recommendation_feedback (
  feedback_id       uuid primary key default extensions.gen_random_uuid(),
  recommendation_id uuid not null references public.recommendations (recommendation_id) on delete cascade,
  user_id           uuid not null references public.users (user_id) on delete cascade,
  feedback_type     public.feedback_type not null,
  created_at        timestamptz not null default now(),
  -- one reaction per recommendation per user; re-reacting is an update
  constraint recommendation_feedback_rec_user_key unique (recommendation_id, user_id)
);

create index recommendation_feedback_user_id_idx on public.recommendation_feedback (user_id);
