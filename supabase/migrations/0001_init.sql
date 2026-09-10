-- GameGPT initial schema.
-- One migration defines the whole walking-skeleton contract. Every table the
-- SysML structure diagram implies has a home here. Idempotent so it can run
-- against a fresh local Postgres or Supabase without hand-holding.

create extension if not exists vector;      -- pgvector: embedding column + cosine search
create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ── users ────────────────────────────────────────────────────────────────
-- No real auth in the skeleton: one seeded dev user, hardcoded UUID from env.
create table if not exists users (
    id          uuid primary key default gen_random_uuid(),
    email       text unique,
    created_at  timestamptz not null default now()
);

-- ── games ────────────────────────────────────────────────────────────────
-- The knowledge base. embedding is nullable until embed_games.py fills it.
create table if not exists games (
    id            uuid primary key default gen_random_uuid(),
    title         text not null,
    description   text,
    genres        text[] not null default '{}',
    tags          text[] not null default '{}',
    release_date  date,
    developer     text,
    review_score  double precision,        -- 0..1
    steam_appid   integer unique,
    embedding     vector(1536),            -- text-embedding-3-small
    created_at    timestamptz not null default now()
);

-- IVFFlat cosine index. Requires ANALYZE after bulk load to be effective;
-- harmless on small skeleton data.
create index if not exists games_embedding_cosine_idx
    on games using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- ── platform_accounts ──────────────────────────────────────────────────────
-- A user's linked account on one platform. Steam is the only real one here.
create table if not exists platform_accounts (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,
    platform     text not null,            -- 'steam' | 'xbox' | 'epic'
    external_id  text not null,            -- steamID64 for steam
    created_at   timestamptz not null default now(),
    unique (user_id, platform, external_id)
);

-- ── owned_games ────────────────────────────────────────────────────────────
-- The user's cross-platform library. Dedup drops recommendations that match.
create table if not exists owned_games (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references users(id) on delete cascade,
    game_id      uuid references games(id) on delete set null,
    platform     text not null default 'steam',
    steam_appid  integer,                  -- kept even when game_id is null
    title        text,                     -- denormalized for title-match dedup
    created_at   timestamptz not null default now(),
    unique (user_id, platform, steam_appid)
);

-- ── queries ────────────────────────────────────────────────────────────────
-- One row per POST /api/recommend. Persisted before recommendations.
create table if not exists queries (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references users(id) on delete cascade,
    text        text not null,
    created_at  timestamptz not null default now()
);

-- ── recommendations ────────────────────────────────────────────────────────
-- The ranked results returned for a query.
create table if not exists recommendations (
    id           uuid primary key default gen_random_uuid(),
    query_id     uuid not null references queries(id) on delete cascade,
    game_id      uuid references games(id) on delete set null,
    rank         integer not null,
    title        text not null,            -- denormalized: results are legible alone
    reason       text not null,
    created_at   timestamptz not null default now(),
    unique (query_id, rank)
);

-- ── recommendation_feedback ────────────────────────────────────────────────
-- Thumbs up/down. Persisted only; does not affect ranking in the skeleton.
create table if not exists recommendation_feedback (
    id           uuid primary key default gen_random_uuid(),
    query_id     uuid not null references queries(id) on delete cascade,
    game_id      uuid references games(id) on delete set null,
    title        text,
    rank         integer,
    vote         text not null check (vote in ('up', 'down')),
    created_at   timestamptz not null default now()
);

create index if not exists owned_games_user_idx on owned_games(user_id);
create index if not exists queries_user_idx on queries(user_id);
create index if not exists recommendations_query_idx on recommendations(query_id);

-- ── seed the single dev user ────────────────────────────────────────────────
insert into users (id, email)
values ('00000000-0000-0000-0000-000000000001', 'dev@gamegpt.local')
on conflict (id) do nothing;
