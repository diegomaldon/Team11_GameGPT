# LLM ranking prompt and response parsing — TM11-69

REQ015 asks for a ranked list of 3 to 5 games, each with an explanation. This is
the last stage of `POST /api/recommend`: `RAGPipeline` hands `LLMService.rank` the
retrieved candidates the user doesn't own (TM11-65, TM11-66), and gets back
ranked `Recommendation`s. The code is `api/services/llm.py`; the tests are
`api/tests/test_llm.py`.

| AC | What meets it | Tests |
|---|---|---|
| AC-01 Ranked titles, each with a one or two sentence explanation | `_build_messages` prompt; `normalise_explanation` keeps two sentences | `test_prompt_*`, `test_a_long_explanation_*` |
| AC-02 Parsed into recommendations rows with rank, explanation and generatedAt | `_picks_to_recs` builds rows; `_stamp` sets `generated_at`; history reads it back | `test_every_result_is_stamped_*`, `test_history_reads_each_results_own_time` |
| AC-03 Output constrained to the retrieved candidate set | `_resolve_pick` checks every pick against the candidates shown | `test_a_made_up_title_*`, `test_every_result_comes_from_the_candidates_given` |
| AC-04 Token usage logged | `llm.usage` per attempt, `llm.ranked` per call | `test_gemini_token_usage_*`, `test_anthropic_token_usage_is_logged` |

## How many

`clamp_recommendation_count` pulls the requested count into 3–5. The pipeline asks
for 3. The hosted `recommendations.rank` column is checked `between 1 and 5`, so a
sixth result would fail the whole history write. Fewer than 3 come back only when
fewer than 3 unowned candidates were retrieved.

## The prompt

Gemini and Claude get the same prompt. The system prompt says to rank only games
from the numbered candidate list, to copy each one's index and title exactly, and
to answer with only a JSON object. The user prompt carries the request and up to
`4 × n` candidates (title, genres, tags, the first 300 characters of the
description, review score), then asks for:

```json
{"recommendations": [
  {"rank": 1, "index": 3, "title": "Unpacking",
   "explanation": "A quiet, wordless puzzle about unpacking boxes. You can play it at your own pace with a podcast on."}
]}
```

The rules ask for exactly `n` games, ranked best first, each game once, and an
explanation of one or two sentences that names something specific about the game.

## Parsing

`_extract_json` takes the outermost `{…}` from the response, so a code fence or a
sentence before the JSON doesn't break it. Then `_picks_to_recs`:

1. Orders the picks by the model's `rank` when every pick has one, and otherwise
   keeps the order they were listed in.
2. Resolves each pick to a candidate (see below). Picks that resolve to no
   candidate are dropped, and so are duplicates.
3. Normalises the explanation: whitespace is collapsed, the first two sentences
   are kept, and the result is capped at 320 characters on a word boundary. A
   full stop after a common abbreviation ("Mr.", "Dr.", "vs.", "e.g.") or an
   initial doesn't end a sentence, so "Inspired by Mr. Robot. Very tense." stays
   whole. "etc." and "No." still do, since they end a sentence as often as not. A
   blank explanation gets a synthesized one that names the query and the game's
   genres. The older `reason` key is still read.
4. If at least one pick survived but fewer than `n` did, it fills the list from the
   unpicked candidates in retrieval order and logs `llm.picks_filled`.
5. If no pick survived, it raises `ValueError`. The provider then gets its one
   retry, then the next provider, then the deterministic ranker.

Each result is a `Recommendation` with `rank`, `game_id`, `title`, `reason` (the
row's `explanation`), `steam_appid`, `review_score` and `generated_at`. All the
results of one call share one UTC `generated_at`, set when the ranking is parsed.

### Saved rows and generated_at

The recommend route saves results in the background (TM11-64) as
`recommendations (query_id, game_id, rank, explanation)`. The row's
`generated_at` comes from the database's `now()` default, not from the app. TM11-64
chose that so a skewed app clock can't reorder history, and a test still checks
it. So the response's `generated_at` and the saved row's are a moment apart.
`GET /api/history` returns the row's own value: `generated_at` on the hosted schema,
`created_at` on the local slice, which has no `generated_at` column.

## Staying inside the candidate set

The model only ever sees unowned, retrieved games, but it can still name a game it
remembers instead of one it was shown. `_resolve_pick` decides which candidate a
pick means:

- **Title and index agree**: that candidate.
- **The title matches a different candidate** (case and spacing ignored): the title
  wins. A model that copies the wrong index next to a real title still meant the
  title.
- **The title matches no candidate**: rejected, even if the index is valid, because
  the explanation is about a game we didn't retrieve. Rejections are logged as
  `llm.picks_rejected` with the count and up to five of the titles.
- **No title**: the index, if it is an integer in range. Bools, strings that aren't
  numbers, and non-objects are rejected.

So every `game_id` returned is one of the candidates passed in, whichever path
produced it. `test_every_result_comes_from_the_candidates_given` checks this for the
parsed path and the offline path.

## Token usage

Every provider attempt logs one line on `gamegpt.llm`. It is written before the
answer is parsed, so an attempt that fails to parse still shows what it cost:

```json
{"logger":"gamegpt.llm","msg":"llm.usage","request_id":"0b6f2c...","provider":"gemini",
 "model":"gemini-3.6-flash","attempt":1,"input_tokens":812,"output_tokens":96,"total_tokens":908}
```

The counts come from Gemini's `usageMetadata` (`promptTokenCount`,
`candidatesTokenCount`) and from Claude's `response.usage` (`input_tokens`,
`output_tokens`). A response without usage logs zeros instead of failing.

Each call also logs one summary line:

```json
{"logger":"gamegpt.llm","msg":"llm.ranked","provider":"gemini","attempts":2,
 "result_count":3,"input_tokens":1624,"output_tokens":192,"total_tokens":1816}
```

`provider` is the one that answered, or `deterministic` when the offline ranker did
(that call costs 0 tokens). A failed attempt logs `llm.attempt_failed` with the
provider and the exception type only. httpx error messages can contain the request
URL, and Gemini's key is in its query string. The tests run these lines through the
JSON formatter to check that the counts survive redaction and the key never appears.

To total a day's spend from Render's logs:

```bash
jq -s 'map(select(.msg == "llm.usage")) | group_by(.provider)
       | map({provider: .[0].provider, calls: length,
              tokens: (map(.total_tokens) | add)})' render.log
```

## Verifying it

```bash
python -m pytest api/tests/test_llm.py -v            # AC-01 to AC-04, no key or network
python -m pytest api/tests/test_query_history.py -v  # generated_at read back (AC-02)
python scripts/export_openapi.py --check             # generated_at is in the contract
```

On the branch's last commit (2026-11-11) the full suite was 1116 passed, 22 skipped and
1 xfailed. `openapi.json` was up to date and the web typecheck passed.
`test_saved_results_read_back_with_generated_at` writes to a real database, so it
only runs on the local schema and was skipped here.

## Not covered here

- **No live provider run.** The tests fake Gemini at the HTTP layer and Claude at
  the client. No real model was called for this ticket, so how often a real model
  breaks the format or names a game outside the list hasn't been measured.
  `llm.picks_rejected` and `llm.attempt_failed` in the deployed logs are where
  that will show.
- **No structured output mode.** Gemini is asked for `application/json` but gets
  no response schema, and Claude gets the format in the prompt only. The parser is
  written to cope with either one drifting from the format.
- **Saved row timestamps**: see [Saved rows and generated_at](#saved-rows-and-generated_at).
