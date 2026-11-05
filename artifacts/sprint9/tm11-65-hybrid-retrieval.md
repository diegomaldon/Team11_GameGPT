# TM11-65 hybrid retrieval: tuning and results

Run 2026-11-05T04:36:25+00:00 on the `legacy` schema (167 games) with `sentence-transformers/all-MiniLM-L6-v2`, against the 20 TM11-63 benchmark prompts. Written by `scripts/eval_hybrid_retrieval.py`.

**Chosen:** pool size 50 per search, metadata weight 0.3 (semantic 0.7), k = 20 candidates handed on. **Deterministic:** yes, two independent runs gave identical full lists for every prompt.

**Retrieval time** (embedding excluded, 100 runs): before p50 96.32 ms / p95 113.53 ms; hybrid p50 110.45 ms / p95 133.55 ms. Each search opens its own connection, as the API does per request.

| | hit@3 | hit@10 | hit@20 | MRR | expected titles in top 20 |
|---|---|---|---|---|---|
| Before (semantic top 20) | 13/20 | 18/20 | 19/20 | 0.653 | 61/81 |
| Hybrid (chosen) | 17/20 | 18/20 | 19/20 | 0.754 | 67/81 |

A hit is any expected title at or above that rank; reference titles never count.

## Grid: pool size × metadata weight

hit@10 / MRR for each setting. Weight 0 is semantic order with ruled-out and named games removed.

| pool \ weight | 0.0 | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 |
|---|---|---|---|---|---|---|
| 10 | 18 / 0.68 | 18 / 0.742 | 18 / 0.75 | 18 / 0.75 | 18 / 0.75 | 18 / 0.75 |
| 20 | 18 / 0.682 | 18 / 0.745 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 |
| 30 | 18 / 0.682 | 18 / 0.745 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 |
| 50 | 18 / 0.682 | 18 / 0.745 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 |
| 100 | 18 / 0.682 | 18 / 0.745 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 | 18 / 0.754 |

## By category

| Category | Before hit@10 | Hybrid hit@10 | Before MRR | Hybrid MRR |
|---|---|---|---|---|
| comparison | 4/5 | 4/5 | 0.45 | 0.567 |
| genre | 5/5 | 5/5 | 1.0 | 1.0 |
| mood | 5/5 | 5/5 | 0.669 | 0.9 |
| platform | 4/5 | 4/5 | 0.494 | 0.548 |

## Per prompt

| Id | Parsed signals | Before rank | Hybrid rank | Hybrid top 3 |
|---|---|---|---|---|
| genre-01 | Tactics | 1 | 1 | XCOM: Enemy Unknown, XCOM 2, Wasteland 3 |
| genre-02 | Metroidvania, difficult | 1 | 1 | Dead Cells, Hollow Knight, Ori and the Will of the Wisps |
| genre-03 | Strategy | 1 | 1 | Stellaris, Sid Meier's Civilization VI, Age of Empires IV |
| genre-04 | Roguelike, Deckbuilder | 1 | 1 | Slay the Spire, Balatro, Loop Hero |
| genre-05 | Horror, tense | 1 | 1 | Alien: Isolation, Lethal Company, Outlast |
| mood-01 | relaxing | 1 | 1 | A Short Hike, Unpacking, Gone Home |
| mood-02 | emotional | 7 | 1 | Night in the Woods, GRIS, Undertale |
| mood-03 | tense | 5 | 2 | Dead by Daylight, Outlast, Alien: Isolation |
| mood-04 | comedy | 1 | 1 | Golf With Your Friends, Overcooked! 2, Fall Guys |
| mood-05 | — | 1 | 1 | Celeste, Super Meat Boy, Dead Cells |
| comparison-01 | like Stardew Valley | 2 | 1 | Dinkum, Terraria, Satisfactory |
| comparison-02 | dark | 1 | 1 | Nioh, Dark Souls III, Divinity: Original Sin 2 |
| comparison-03 | Action, Roguelike | 2 | 2 | Hades, Hades II, Vampire Survivors |
| comparison-04 | — | - | - | Fez, Hitman 3, Factorio |
| comparison-05 | like Firewatch | 4 | 3 | The Long Dark, Night in the Woods, Journey |
| platform-01 | cozy, xbox | 1 | 1 | Stardew Valley, Dinkum, Ooblets |
| platform-02 | Co-op, Shooter, steam | 1 | 1 | Killing Floor 2, Warhammer: Vermintide 2, Team Fortress 2 |
| platform-03 | Action, Roguelike, epic | 19 | 14 | Slay the Spire, Spelunky 2, Loop Hero |
| platform-04 | RPG, story-rich, xbox | 4 | 2 | Fallout: New Vegas, Baldur's Gate 3, Wasteland 3 |
| platform-05 | steam | 6 | 6 | Rust, Dinkum, Don't Starve Together |

## Parser gaps this run found

Prompts where the named game wasn't recognised (so it isn't removed from the answers) or nothing was parsed (so the prompt ranks on similarity alone). These are TM11-62 vocabulary and cue gaps, left for a follow-up rather than fitted to these 20 prompts.

| Id | Prompt | Gap |
|---|---|---|
| mood-05 | brutally hard but rewarding when I finally beat it | no signals parsed |
| comparison-02 | something like Dark Souls but with samurai and ninjas | named Dark Souls III not recognised |
| comparison-03 | I finished Hades, what other fast action roguelikes should I try | named Hades not recognised |
| comparison-04 | Factorio but in 3D and a bit less overwhelming | named Factorio not recognised |
