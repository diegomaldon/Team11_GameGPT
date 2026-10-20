# TM11-40 vector index check

Run 2026-10-17T18:31:37+00:00 with `sentence-transformers/all-MiniLM-L6-v2`, top 10, 10 timed searches per query. Produced by `scripts/eval_vector_index.py`.

| Measure | Result |
|---|---|
| Recall@10 (20 known queries) | **20/20** (100%) |
| Mean rank of the expected game, when found | 1 |
| Search latency p50 / p95 / max | 99.59 / 115.78 / 126.38 ms (200 runs) |
| Of which: opening the connection, p50 | 41.47 ms |
| Query execution in Postgres, planner's choice / forced HNSW | 0.756 / 0.22 ms |
| Query embedding p50 / p95 | 23.57 / 25.87 ms |
| HNSW index size | 344.0 KB |
| game_embeddings total size | 1008.0 KB |
| Rows for the model / games in catalogue | 167 / 167 |
| Duplicate (game_id, model) rows | 0 |
| Planner picks the index (default settings) | False |
| Index serves the query (seq scan off) | True |

Search latency is measured the way the API runs it: `VectorStore.top_k` opens a new connection per call. Postgres executes the search in under a millisecond, so almost all of the end-to-end time is client side: opening the connection, then the query round trips. Pooling connections (not in this story) is where that time would come back. These numbers are from a local Docker Postgres, not Supabase. At this catalogue size Postgres prefers a sequential scan to the HNSW index, which is the cheaper plan for a table this small; the index serves the same query when the planner is steered to it, and becomes the planner's choice as the table grows.

## Queries

| # | Query | Expected | Hit | Rank | Top 3 returned |
|---|---|---|---|---|---|
| 1 | farm life sim where you grow crops and make friends in town | Dinkum, My Time at Portia, Stardew Valley | yes | 1 | Stardew Valley, Dinkum, RimWorld |
| 2 | first-person puzzles with a portal gun | Portal, Portal 2 | yes | 1 | Portal 2, Portal, Hitman 3 |
| 3 | metroidvania in a ruined bug kingdom | Hollow Knight | yes | 1 | Hollow Knight, Dead Cells, Cave Story+ |
| 4 | hard platformer about climbing a mountain | Celeste | yes | 1 | Celeste, A Short Hike, Journey |
| 5 | roguelike where you fight your way out of the underworld | Hades, Hades II | yes | 1 | Hades, Vampire Survivors, Dead Cells |
| 6 | deckbuilding roguelike card game | Slay the Spire | yes | 1 | Slay the Spire, Balatro, Loop Hero |
| 7 | build automated factories with conveyor belts | Factorio, Satisfactory | yes | 1 | Factorio, Satisfactory, Recettear: An Item Shop's Tale |
| 8 | survive under the ocean on an alien planet | Subnautica | yes | 1 | Subnautica, Raft, Sea of Thieves |
| 9 | four player co-op zombie shooter | Left 4 Dead, Left 4 Dead 2 | yes | 1 | Left 4 Dead, Left 4 Dead 2, Killing Floor 2 |
| 10 | check passports at a border checkpoint | Papers, Please | yes | 1 | Papers, Please, Dead Cells, Outlast |
| 11 | figure out what happened to the crew of a ghost ship | Return of the Obra Dinn | yes | 1 | Return of the Obra Dinn, Among Us, Cozy Grove |
| 12 | fire lookout in the woods talking to someone over a radio | Firewatch | yes | 1 | Firewatch, Night in the Woods, The Long Dark |
| 13 | hide from an alien hunting you on a space station | Alien: Isolation | yes | 1 | Alien: Isolation, Prey (2017), XCOM: Enemy Unknown |
| 14 | city builder with zoning and traffic | Cities: Skylines | yes | 1 | Cities: Skylines, Anno 1800, Dinkum |
| 15 | medieval dynasty strategy with marriages and scheming | Crusader Kings III | yes | 1 | Crusader Kings III, Mount & Blade II: Bannerlord, Kingdom Come: Deliverance |
| 16 | story game two players have to play together | A Way Out, It Takes Two, Unravel Two | yes | 1 | A Way Out, It Takes Two, Team Fortress 2 |
| 17 | calm game about unpacking boxes in a new home | Unpacking | yes | 1 | Unpacking, Satisfactory, Gone Home |
| 18 | chaotic co-op cooking in a busy kitchen | Overcooked! 2 | yes | 1 | Overcooked! 2, Killing Floor 2, Unravel Two |
| 19 | dwarves mining caves and fighting bugs with friends | Deep Rock Galactic | yes | 1 | Deep Rock Galactic, Valheim, Stardew Valley |
| 20 | tactical competitive shooter where every bullet counts | Counter-Strike 2 | yes | 1 | Counter-Strike 2, Enter the Gungeon, Team Fortress 2 |
