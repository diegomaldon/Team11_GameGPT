# Retrieval quality on the benchmark (TM11-67)

How well does retrieval answer the 20 TM11-63 benchmark prompts, did the
TM11-65 weighting help, and where is it weakest? Evidence for the final report.

- Run: `scripts/eval_retrieval_quality.py` (read-only against the database)
- Scoring: `api/services/retrieval_quality.py`, tested in `api/tests/test_retrieval_quality.py`
  (CI **API tests** job)
- Results: [`artifacts/sprint9/tm11-67-retrieval-quality.md`](../artifacts/sprint9/tm11-67-retrieval-quality.md)
  and the full per-prompt record in the `.json` next to it
- Measured on: the hosted Supabase catalogue (1005 games), `all-MiniLM-L6-v2`,
  2026-11-06. A second run gave identical results.

## What is measured

**Precision at 5 (P@5):** expected titles in the top 5 results divided by 5.
A game the prompt names ("like Stardew Valley") never counts as a hit.

Most prompts list four expected titles, so a perfect top 5 scores 0.8. Some list
only one or two. *Normalised* P@5 divides by the best each prompt allows, and
the category ranking uses it so a category isn't called weak just because its
prompts expect fewer titles.

**Before:** the top results by cosine similarity alone, as the pipeline worked
before TM11-65. **After:** hybrid retrieval as it runs today, with semantic 0.7,
metadata 0.3, pool 50, and named and ruled-out games removed.

## Headline

| | mean P@5 | mean normalised | MRR | prompts with no hit in top 5 |
|---|---|---|---|---|
| Before | 0.25 | 0.375 | 0.537 | 7/20 |
| After | **0.32** | **0.463** | **0.633** | **4/20** |

**5 prompts improved, 0 regressed, 15 unchanged.** The weighting change is a
clear improvement with no regressions. It moved hits *into* the top 5 for
mood-02, mood-03, comparison-02, platform-01 and platform-04.

## Before and after the weighting change (AC-02)

The metadata-weight sweep separates the two halves of TM11-65:

| Metadata weight | mean P@5 |
|---|---|
| Before (similarity only) | 0.25 |
| 0.0 (removal only) | 0.26 |
| 0.1 | 0.31 |
| 0.2 | 0.32 |
| **0.3 (chosen)** | **0.32** |
| 0.4 / 0.5 | 0.31 |

- Removing named and ruled-out games alone barely moves P@5 (+0.01). Almost the
  whole gain comes from the **weighting**.
- 0.2–0.3 is the plateau. Above it, genre prompts start to lose (0.44 → 0.40),
  because a strict genre match begins to outrank a closer game. Genre peaks at
  0.1 (0.48), but mood and platform gain more at 0.2–0.3.
- **The tuned 0.7 / 0.3 holds on the hosted catalogue, which is six times the
  size of the 167-game slice TM11-65 tuned on. No retune is recommended.**

Absolute numbers are lower than TM11-65's (MRR 0.754 there) because the
catalogue now has 1005 games, so there are far more near-miss games competing
for each slot. See also *Limits* below.

## By category: the weakest are comparison, then platform (AC-03)

| Rank | Category | After P@5 | After normalised | Change in P@5 | No hit in top 5 |
|---|---|---|---|---|---|
| 1 (weakest) | **comparison** | 0.12 | 0.19 | +0.04 | 2/5 |
| 2 | **platform** | 0.28 | 0.36 | +0.12 | 1/5 |
| 3 | mood | 0.44 | 0.44 | +0.12 | 1/5 |
| 4 (strongest) | genre | 0.44 | 0.86 | 0 | 0/5 |

### Comparison ("like X but Y"): the weakest by a wide margin

The weighting helps least here, because the problem is upstream of it. The
query parser (TM11-62) mostly fails to turn "like X" into anything retrieval can use:

| Prompt | What went wrong | Evidence |
|---|---|---|
| comparison-04 "Factorio but in 3D…" | "X but …" at the start isn't a comparison cue, so Factorio isn't recognised and ranks **#1** | top 5 has none of the one expected title, Satisfactory |
| comparison-03 "I finished Hades, what other…" | "I finished X" isn't a cue, so Hades ranks **#1** with Hades II behind it | P@5 0.2 |
| comparison-02 "like Dark Souls but with samurai…" | "Dark Souls" resolves to *DARK SOULS™: REMASTERED*; Dark Souls III and Dark Souls II are not removed and take two of five slots | Sekiro squeezed to #5 |
| comparison-01 "like Stardew Valley but with more crafting…" | Stardew Valley *is* removed, but nothing about it carries into the search. Similarity follows "crafting and building" to survival-crafters (ASTRONEER, The Planet Crafter) instead of cozy life sims | 0 of 4 expected |
| comparison-05 "like Firewatch where you walk and explore" | Recognised and removed; one expected hit (Journey). Similarity is pulled by the word "story" (*Stories: The Path of Destinies*, *A Story About My Uncle*) | P@5 0.2 |

The named game, or its sequels, occupying the top slots is the single
largest loss in the benchmark.

### Platform: a constraint the parser half-reads

- **platform-05** "survive on a remote island and build a base with friends, on
  Steam" scores 0.0. The benchmark's intended filter is `Survival` on Steam, but
  the parser reads only `steam`. "Survive" isn't in the genre vocabulary, so
  the metadata leg filters to Steam (most of the catalogue) and adds nothing.
  The first expected game is at rank 9.
- **platform-03** "action roguelike on the Epic Games Store" expects only Hades
  and Hades II. It finds Hades at #1 but not Hades II.
- **platform-01** and **platform-04** are the category's two biggest gains
  (+0.2, +0.4). The misses there are reasonable answers the benchmark doesn't
  list: Cozy Grove and Spiritfarer for cozy farming, Fallout: New Vegas and
  Divinity: Original Sin for a choice-driven RPG.

### Mood and genre

- **mood-05** "brutally hard but rewarding" parses to nothing, so it ranks on
  similarity alone. The first expected game is at rank 40, and *Brutal Legend*
  appears on the word "brutally".
- **mood-02** "…make me cry" pulls *Cry of Fear* on the word "cry". Surface-word
  matches like this are a known weakness of a small sentence-embedding model.
- **genre** prompts are the strongest (normalised 0.86, every prompt hits at #1
  or #2). Their raw P@5 looks lower only because several expect just one or two
  titles.

## What would improve it

These are candidate follow-up stories. None are fitted to these 20 prompts.
Fixing them should be measured by re-running the script.

1. **Comparison cues in the parser (TM11-62):** recognise "I finished X",
   "X but …" and "something like X". This fixes comparison-03 and -04 outright.
2. **Franchise-aware removal:** when a named game resolves, also drop its
   sequels and editions, and normalise ™/® when matching (comparison-02, -03).
3. **Use the named game as a signal, not only a removal:** add its genres and
   tags as metadata signals, so "like Stardew Valley" searches for cozy farming
   (comparison-01).
4. **Vocabulary gaps:** "hard / brutal / punishing" → *difficult*; "survive" →
   *Survival* (mood-05, platform-05).
5. **Refresh the benchmark's expected sets for the hosted catalogue:** they were
   drawn from the 167-game fixture, so several reasonable answers from the
   larger catalogue count as misses. That needs a `version` bump (see
   `docs/query-benchmark.md`).

## Limits

- **P@5 is a lower bound.** Expected titles are "the good answers, not every
  acceptable one" (TM11-63). On a 1005-game catalogue many top-5 misses are
  defensible, so read the numbers as relative (before vs after, category vs
  category) more than absolute.
- **Retrieval only.** This measures the candidates handed to the LLM, not the
  final three recommendations after dedup and LLM ranking.
- **Parsed signals, not request filters.** Like `eval_hybrid_retrieval.py`, this
  retrieves from what the parser reads in the prompt. The benchmark's `filters`
  field (what the UI could send explicitly) isn't applied, so platform-05 is
  scored as a user typing the sentence, not one using the genre filter.
- **20 prompts, 5 per category.** One prompt moves a category mean by 0.04–0.08
  P@5, so treat small category differences as noise. The comparison result is
  well outside that range.
