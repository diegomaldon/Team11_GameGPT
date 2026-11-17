# TM11-67 retrieval quality: precision at 5 on the benchmark

Run 2026-11-17T15:49:49+00:00 on the `hosted` schema (1005 games) with `sentence-transformers/all-MiniLM-L6-v2`, against the 20 TM11-63 benchmark prompts. Written by `scripts/eval_retrieval_quality.py`; read-only against the database.

**Before:** top results by similarity alone (the pipeline before TM11-65). **After:** hybrid retrieval at semantic 0.7 / metadata 0.3, pool 50 (the current pipeline).

P@5 is expected titles in the top 5 divided by 5. Most prompts list four expected titles, so a perfect answer scores 0.8; *normalised* divides by what each prompt allows. A title the prompt names ("like X") never counts.

| | mean P@5 | mean normalised | MRR | prompts with no hit in top 5 |
|---|---|---|---|---|
| Before | 0.24 | 0.365 | 0.516 | 8/20 |
| After | 0.34 | 0.503 | 0.637 | 4/20 |

Per prompt: **6 improved, 0 regressed, 14 unchanged.**

## By category

Weakest first (after, by mean normalised P@5, then MRR).

| Category | Before P@5 | After P@5 | Change | Before normalised | After normalised | After no-hit prompts |
|---|---|---|---|---|---|---|
| comparison | 0.04 | 0.12 | +0.080 | 0.05 | 0.25 | 3/5 |
| mood | 0.32 | 0.44 | +0.120 | 0.32 | 0.44 | 1/5 |
| platform | 0.16 | 0.36 | +0.200 | 0.23 | 0.46 | 0/5 |
| genre | 0.44 | 0.44 | 0 | 0.86 | 0.86 | 0/5 |

## Metadata weight sweep

Mean P@5 at pool 50. Weight 0.0 is similarity order with named and ruled-out games removed, so the step from *Before* to 0.0 is the removal alone and the steps after it are the weighting.

| Metadata weight | all | genre | mood | comparison | platform |
|---|---|---|---|---|---|
| Before | 0.24 | 0.44 | 0.32 | 0.04 | 0.16 |
| 0.0 | 0.26 | 0.44 | 0.32 | 0.12 | 0.16 |
| 0.1 | 0.32 | 0.48 | 0.44 | 0.12 | 0.24 |
| 0.2 | 0.34 | 0.44 | 0.44 | 0.12 | 0.36 |
| 0.3 (chosen) | 0.34 | 0.44 | 0.44 | 0.12 | 0.36 |
| 0.4 | 0.33 | 0.4 | 0.44 | 0.12 | 0.36 |
| 0.5 | 0.33 | 0.4 | 0.44 | 0.12 | 0.36 |

## Per prompt

| Id | Best possible | Before P@5 | After P@5 | Change | After first hit | After top 5 |
|---|---|---|---|---|---|---|
| genre-01 | 0.4 | 0.4 | 0.4 | 0 | 1 | XCOM: Enemy Unknown, XCOM 2, Wasteland 3, Sabre Team, Squad |
| genre-02 | 1.0 | 0.8 | 0.8 | 0 | 1 | Hollow Knight, Dead Cells, Cave Story+, Ori and the Will of the Wisps, Blasphemous |
| genre-03 | 0.2 | 0.2 | 0.2 | 0 | 2 | STAR WARS™ Empire at War - Gold Pack, Stellaris, ENDLESS Space™ 2, X4: Foundations, Europa Universalis IV |
| genre-04 | 0.4 | 0.4 | 0.4 | 0 | 1 | Slay the Spire, Balatro, Loop Hero, Cult of the Lamb, Hades |
| genre-05 | 0.8 | 0.4 | 0.4 | 0 | 1 | Alien: Isolation, Lethal Company, Outlast, Dead by Daylight, Dead Space (2023) |
| mood-01 | 1.0 | 0.6 | 0.6 | 0 | 1 | Unpacking, A Short Hike, Cozy Grove, PowerWash Simulator, Potion Craft |
| mood-02 | 1.0 | 0.0 | 0.2 | +0.200 | 3 | To the Moon, Detroit: Become Human, Undertale, Cry of Fear, Secret in Story |
| mood-03 | 1.0 | 0.4 | 0.8 | +0.400 | 1 | Amnesia: The Dark Descent, Alien: Isolation, Phasmophobia, Dead by Daylight, Outlast |
| mood-04 | 1.0 | 0.6 | 0.6 | 0 | 1 | Human: Fall Flat, Overcooked! 2, Helldivers 2, Golf With Your Friends, Draw & Guess |
| mood-05 | 1.0 | 0.0 | 0.0 | 0 | 8 | Getting Over It with Bennett Foddy, Blasphemous, Beat Saber, Turbo Pug, The Surge |
| comparison-01 | 0.8 | 0.0 | 0.0 | 0 | - | ASTRONEER, The Planet Crafter, Don't Starve, Craftopia, Star Conflict |
| comparison-02 | 0.4 | 0.0 | 0.4 | +0.400 | 3 | Yakuza 0, SoulWorker - Anime Action MMO, Sekiro: Shadows Die Twice, Mark of the Ninja, Nioh |
| comparison-03 | 0.8 | 0.0 | 0.0 | 0 | 8 | Vampire Survivors, Neon Abyss, Deathmatch Classic, Spelunky 2, Total War: WARHAMMER III |
| comparison-04 | 0.2 | 0.0 | 0.0 | 0 | - | BLOCKPOST LEGACY, BLOCKADE 3D, Crysis, Far Cry 3, Crysis 3 Remastered |
| comparison-05 | 0.8 | 0.2 | 0.2 | 0 | 2 | Stories: The Path of Destinies, Journey, A Story About My Uncle, Mirror's Edge™, Monster Hunter Wilds |
| platform-01 | 0.8 | 0.2 | 0.4 | +0.200 | 1 | Stardew Valley, Cozy Grove, Unpacking, Spiritfarer, My Time at Portia |
| platform-02 | 1.0 | 0.4 | 0.4 | 0 | 1 | Killing Floor 2, Warhammer: Vermintide 2, Counter-Strike: Global Offensive, Helldivers 2, Team Fortress 2 |
| platform-03 | 0.4 | 0.2 | 0.2 | 0 | 1 | Hades, Tomb Raider, Slay the Spire, Spelunky 2, The Binding of Isaac: Rebirth |
| platform-04 | 1.0 | 0.0 | 0.4 | +0.400 | 2 | Fallout: New Vegas, The Witcher 3: Wild Hunt, Divinity: Original Sin, Wasteland 3, Baldur's Gate 3 |
| platform-05 | 0.8 | 0.0 | 0.4 | +0.400 | 3 | Palworld, Rust, Raft, Terraria, The Forest |

## Catalogue coverage

Every expected title is in this catalogue.
