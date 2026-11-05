# TM11-159 — hosted catalogue rebuild (Supabase)

Run on 2026-11-05 against the hosted Supabase project, connected as `postgres`
through the Session pooler, following docs/RUNBOOK.md
("Rebuilding the hosted catalogue without RAWG"). Agreed with the team beforehand.

## Before

`verify_catalogue.py`: **FAIL**. 16 games (15 RAWG-era with `rawg_id` and no
`steam_appid`, plus the `REQ005 Deletion Test Game` row), 16 of 16 embedded,
2 of 69 benchmark titles present. A copy of the 16 `games` and 16
`game_embeddings` rows was saved locally before any write.

The hosted database was missing three migrations. Only the one this ticket
needs was applied:

| Migration | Applied here |
|---|---|
| `20261020130000_game_embeddings_template_version.sql` | **yes**: `embed_catalogue.py` writes `template_version`; the 16 existing vectors became `v0` |
| `20261018120000_game_embeddings_hnsw_index.sql` | no (TM11-40) |
| `20261020120000_owned_games_external_id.sql` | no (library import) |

## Steps

| Step | Command | Result |
|---|---|---|
| 1. Dry run | `ingest_games.py --source-func catalogue_source:fetch_steam_enriched_catalogue --source steam-seed --target 167 --dry-run` | 167 valid, 0 rejected |
| 2. Load | same, `--run-id steam-seed-01` | **inserted 158, updated 9, rejected 0**, 22.3s, exit 0 |
| 3. Re-run | same, `--run-id steam-seed-02` | **inserted 0, updated 0, unchanged 167, rejected 0**, exit 0 |
| 4. Embed | `embed_catalogue.py` | **174 of 174** embedded with all-MiniLM-L6-v2 (158 new, 16 changed), 0 failed, 10.6s |
| 5. Verify | `verify_catalogue.py` | **PASS**: see [tm11-159-catalogue-check.md](tm11-159-catalogue-check.md) |

The 9 updates are RAWG-era games adopted by title (each kept its `game_id` and
`rawg_id`, gained its `steam_appid`): Half-Life 2, Portal 2, Left 4 Dead 2,
The Witcher 3: Wild Hunt, Grand Theft Auto V, Red Dead Redemption 2,
The Elder Scrolls V: Skyrim, Portal, God of War (2018). Their data columns now
hold the seed + Steam values, so their `XBOX` platform and RAWG tags are gone
(the team's choice). Left as they were: BioShock, BioShock Infinite,
Borderlands 2, Counter-Strike: Global Offensive, Life is Strange, Tomb Raider,
and the REQ005 test row.

## After

| Games | steam_appid | header_image_url | critic_score | publishers | embedded |
|---|---|---|---|---|---|
| 174 | 167 | 173 | 151 | 171 | 174 |

`POST /api/search` (in-process app, hosted database) returns the new games:

| Query | Top 5 |
|---|---|
| cozy farming life sim with crafting | Stardew Valley, My Time at Portia, Cozy Grove, Palworld, Potion Craft |
| roguelike deckbuilder | Slay the Spire, Balatro, Loop Hero, Hades, Spelunky 2 |
| hard precise platformer | Celeste, Shovel Knight, Super Meat Boy, LIMBO, Fez |

`POST /api/recommend` was not called here because it writes query history to
the hosted database; it ranks from the same `game_embeddings` rows.

## Known gaps

- Xbox and Epic availability: Steam doesn't report it, so the 158 new games are
  `{STEAM}` only and benchmark prompts platform-01/03/04 still can't be scored.
- The HNSW index and `owned_games.external_id` migrations are not applied on the
  hosted database.
