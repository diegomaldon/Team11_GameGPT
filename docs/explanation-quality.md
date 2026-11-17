# Explanation quality (TM11-70)

REQ015 asks for a plain-language reason with each recommendation, not the
game's genre tags restated. Does the ranking prompt deliver that, and did the
TM11-70 revision help? Evidence for the final report.

- Prompt: `_build_messages` in `api/services/llm.py`. TM11-70 extends the
  `explanation` rule from TM11-69 (PR #61); the response schema is unchanged.
- Run: `scripts/eval_explanations.py` (no database; seed catalogue)
- Checks: `api/services/explanation_quality.py`, tested in
  `api/tests/test_explanation_quality.py` (CI **explanation quality** job)
- Samples: [`artifacts/sprint10/tm11-70-explanations.md`](../artifacts/sprint10/tm11-70-explanations.md),
  every pick in the `.json` next to it

## What changed in the prompt

TM11-69's rule asked for "one or two sentences saying why this game fits the
request. Name something specific about the game." TM11-70 keeps that and adds
that the explanation should:

1. answer the request in the player's own terms (a mood, a situation, a game
   they compared to) and say how the game delivers it
2. point to something concrete from the description: what you do, where it is
   set, how it feels
3. not list genre or tag labels, and not use stock phrases ("perfect match",
   "fits your query", "great choice")
4. say what a game shares with, or does differently from, one the player named
5. say which part of the request a game only partly fits

## How it was measured

Both prompts ranked **the same candidates** for each benchmark prompt
(retrieved from the 167-game seed catalogue with the local embedding model,
the query parser and the hybrid merge), so any difference is the prompt's.
Each explanation was checked automatically (uses a word from the request;
restates fewer than two of the game's own labels; no stock phrase) and then
read in full. The review below is of those 21 explanations.

The run used `gemini-3-flash-preview`. Production's `gemini-3.6-flash`
returned 503 (overloaded) for every call that afternoon. The comparison only
needs one model for both prompts. The free tier allows 20 requests a day per
model, so the run covers five prompts, one from every category except genre,
which gets two. Rate limits and timeouts cost three of the ten rankings:
mood-05 *after*, and both versions of comparison-03. 21 explanations came back:
12 *before* across 4 prompts, 9 *after* across 3.

## Results

Like for like, on the three prompts where both versions answered (genre-04,
mood-01, platform-05; nine explanations each):

| | passes the checks | uses the request's words | restates 2+ labels | stock phrase |
|---|---|---|---|---|
| Before (TM11-69 prompt) | 4/9 | 7/9 | 2 | 1 |
| After (TM11-70 prompt) | **9/9** | **9/9** | **0** | **0** |

Across everything that came back: before 6/12 pass, after 9/9.

## Review of the 21 explanations

**Before** (12, TM11-69 prompt). The reasons were already specific about the
games. TM11-69's "name something specific" works. The two failures REQ015
names show up anyway:

- **Restated labels.** genre-04's top pick opens "This is the definitive
  roguelike deckbuilder…", and Balatro is "a unique poker-themed roguelike".
  That's the genre read back to a player who just typed it.
- **Not answering the request.** For mood-01 ("calm and low stress to unwind
  with after a long day"), A Short Hike and Unpacking are described well, but
  neither reason mentions unwinding, stress or the end of a day. They describe
  the game, not why it suits *this* request.
- **Stock phrasing.** platform-05's Raft starts "This game perfectly matches
  your request…" before getting to the useful part.
- Good examples exist. The Forest and Rust for platform-05, and Super Meat Boy
  for mood-05 ("the definition of brutally hard… every successful level feel[s]
  like a massive victory"), answer the request directly.

**After** (9, TM11-70 prompt). Every explanation passes, and on reading:

- Each one names what was asked for. Coffee Talk is "an ideal way to quietly
  unwind after a long day". A Short Hike is "a gentle, low stress environment".
  Raft is "you and your friends … build a massive floating base".
- Each one points to something you do. "Stack joker synergies and manipulate
  poker hands", "unpack boxes into new homes across someone's life",
  "scavenging debris".
- No genre lists. The single label the checker found ("multiplayer" for Rust)
  is used in a sentence, not as a tag.
- **Weaknesses.** genre-04's three reasons all repeat "build a new deck", which
  is the request's own phrase echoed back rather than paraphrased. Slay the
  Spire's "deceptively deep and challenging experience" is close to filler.
  Neither breaks REQ015, but rule 1 can make the model parrot.

**Verdict.** The revision does what REQ015 asks on every explanation that came
back. The before prompt was decent, but 5 of its 9 like-for-like reasons
restated labels, skipped the request or used a stock phrase.

## Limits

- **Small sample.** 21 explanations over five prompts, and only three have both
  versions. That is enough to see the failure modes go away, not to put a
  precise rate on them. comparison-03 got no answers, so rule 4 (comparing to
  a named game) is untested live. Rerunning `--ids comparison-01,comparison-03`
  on a fresh day's quota would cover it.
- **The checks are crude on purpose.** Word overlap and label matching can
  misfire. Celeste "incredibly difficult… extreme precision" is flagged for
  repeating its `difficult` and `precision` tags, though it reads naturally.
  They compare two prompts on the same candidates. They don't grade a single
  reason.
- **One model, one day, temperature 0.2.** A rerun gives similar but not
  identical wording.
