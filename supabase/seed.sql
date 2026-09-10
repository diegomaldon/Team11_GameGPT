-- Dev-user owned games.
--
-- Seeds a handful of `owned_games` rows for the single seeded dev user
-- (00000000-0000-0000-0000-000000000001, created by migration 0001) so the
-- dedup step in the RAG pipeline has something real to drop. Each title and
-- steam_appid below also appears in scripts/fixtures/games.json, so once
-- scripts/seed_games.py has run, these will visibly disappear from
-- recommendation results for the dev user.
--
-- game_id is left null on purpose: DeduplicationService matches on
-- steam_appid first and normalized title second (per the RAG contract), not
-- on a games.id foreign key, so this file doesn't need to know the games
-- table's generated UUIDs and can run before or after seed_games.py.
--
-- Idempotent: `on conflict (user_id, platform, steam_appid) do nothing`
-- mirrors the unique constraint on owned_games, so re-running this file
-- never duplicates a row.

insert into owned_games (user_id, platform, steam_appid, title, game_id)
values
    ('00000000-0000-0000-0000-000000000001', 'steam', 220,    'Half-Life 2',   null),
    ('00000000-0000-0000-0000-000000000001', 'steam', 620,    'Portal 2',      null),
    ('00000000-0000-0000-0000-000000000001', 'steam', 413150, 'Stardew Valley', null),
    ('00000000-0000-0000-0000-000000000001', 'steam', 367520, 'Hollow Knight', null),
    ('00000000-0000-0000-0000-000000000001', 'steam', 504230, 'Celeste',       null)
on conflict (user_id, platform, steam_appid) do nothing;
