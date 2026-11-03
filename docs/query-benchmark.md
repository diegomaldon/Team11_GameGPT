# Retrieval query benchmark (TM11-63)

Twenty prompts that a player might type, each with the catalogue games a good
answer includes. It lets us measure retrieval quality instead of guessing at it,
and every evaluation scores the same questions.

- Fixture: `api/fixtures/query_benchmark.json`
- Loader: `api/services/query_benchmark.py` (`load_query_benchmark`, `BenchmarkQuery`)
- Tests: `api/tests/test_query_benchmark.py`, run in the CI **API tests** job
- Used by: `scripts/eval_vector_index.py` (TM11-40), `scripts/eval_search_latency.py`
  (TM11-42). The TM11-67 quality evaluation should import the same loader.

## The prompts

| Category | Count | What it tests |
|---|---|---|
| `genre` | 5 | A named genre or sub-genre ("roguelike deckbuilder", "metroidvania"). |
| `mood` | 5 | Feel words with no genre in them ("calm and low stress", "make me cry"). |
| `comparison` | 5 | "Like X but Y". The game named is listed in `reference_titles`, not `expected_titles`. |
| `platform` | 5 | A store constraint, carried as `filters.platforms`; one also sets `filters.genres`. |

## Entry format

```json
{
  "id": "comparison-01",
  "category": "comparison",
  "prompt": "like Stardew Valley but with more crafting and building",
  "filters": {"platforms": [], "genres": []},
  "expected_titles": ["My Time at Portia", "Dinkum", "Ooblets", "Slime Rancher"],
  "reference_titles": ["Stardew Valley"],
  "note": "Cozy life sims with crafting. The reference game itself is not a good answer."
}
```

- `filters` has the same shape as the `POST /api/search` body and becomes a
  `SearchFilters`, so it can go straight to `VectorStore.top_k`.
- `expected_titles` are exact `games.title` values from
  `scripts/fixtures/games.json`. The tests fail if one is missing, so renaming or
  dropping a catalogue game shows up in CI instead of as a quiet fall in recall.
- `BenchmarkQuery.hit_rank(titles)` is the 1-based rank of the first expected
  title in a result list, or `None`. A reference title never counts as a hit.

## How the expected titles were chosen

- Read from each game's genres and tags in the catalogue fixture, not from what
  the model currently returns, so the set doesn't just confirm today's ranking.
- They are meant to be the good answers, not every acceptable one. A top-10
  list can be reasonable and still miss them all; that is what the metric
  should expose.
- Platform prompts rely on public store availability (for example, Dinkum has no
  Xbox release, so it is left out of `platform-01`). The catalogue fixture has no
  platform data, so this can only be confirmed against `games.available_platforms`
  on the hosted schema.
- On the local `0001_init.sql` slice every game counts as Steam-only, so the
  Xbox and Epic prompts (`platform-01`, `platform-03`, `platform-04`) return
  nothing there. Only the hosted schema scores them.

## Changing the set

Changing a prompt or its expected titles changes every number measured against
it. Bump `version` in the fixture and say why in the commit, and don't compare
recall across versions. The sprint 6/7 artifacts were measured on the older
TM11-40 query set and are kept as they were.
