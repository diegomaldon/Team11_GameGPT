"""Score retrieval quality against the TM11-63 benchmark (TM11-67).

Precision at k is the share of the first k results that are expected titles:

    P@k = |top k ∩ expected_titles| / k

Most benchmark prompts list four expected titles, so a perfect top 5 there
scores 0.8, not 1.0. `attainable` is the best P@k the prompt allows
(min(len(expected), k) / k) and `normalised` is P@k divided by it, so prompts
with different-sized answer sets can be compared and averaged fairly. Both are
reported; P@k is the headline number the acceptance criterion asks for.

A reference title (the game a "like X" prompt names) is never a hit, the same
rule BenchmarkQuery.hit_rank applies.

Pure functions over title lists: no database, no model. The live run that
feeds them is scripts/eval_retrieval_quality.py.

Not a SysML block: evaluation code, not part of the running system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from api.services.query_benchmark import BenchmarkQuery

PRECISION_K = 5


@dataclass(frozen=True)
class PromptScore:
    """One benchmark prompt scored on one ranked result list."""

    id: str
    category: str
    prompt: str
    k: int
    hits: int  # expected titles in the top k
    precision: float  # hits / k
    attainable: float  # min(len(expected), k) / k
    first_hit_rank: int | None  # 1-based, over the whole list, or None
    top_k: tuple[str, ...]

    @property
    def normalised(self) -> float:
        """P@k as a share of the best this prompt allows (0..1)."""
        return self.precision / self.attainable if self.attainable else 0.0


def precision_at(query: BenchmarkQuery, titles: Sequence[str], k: int = PRECISION_K) -> float:
    """Share of the first `k` titles that are expected answers for `query`."""
    if k <= 0:
        raise ValueError("k must be positive")
    expected = set(query.expected_titles)
    return sum(1 for t in _distinct(titles)[:k] if t in expected) / k


def attainable_precision(query: BenchmarkQuery, k: int = PRECISION_K) -> float:
    """The highest P@k this prompt can score, given how many titles it expects."""
    if k <= 0:
        raise ValueError("k must be positive")
    return min(len(set(query.expected_titles)), k) / k


def score_prompt(query: BenchmarkQuery, titles: Sequence[str], k: int = PRECISION_K) -> PromptScore:
    """Score one prompt's ranked result titles."""
    ranked = _distinct(titles)
    expected = set(query.expected_titles)
    top = tuple(ranked[:k])
    hits = sum(1 for t in top if t in expected)
    return PromptScore(
        id=query.id,
        category=query.category,
        prompt=query.prompt,
        k=k,
        hits=hits,
        precision=round(hits / k, 3),
        attainable=round(attainable_precision(query, k), 3),
        first_hit_rank=query.hit_rank(ranked),
        top_k=top,
    )


# ───────────────────── summaries, before/after, weakest ─────────────────────


@dataclass(frozen=True)
class Summary:
    """Mean scores over a group of prompts (one category, or all of them)."""

    name: str
    prompts: int
    mean_precision: float
    mean_normalised: float
    mrr: float  # mean of 1 / first_hit_rank, 0 for a prompt with no hit
    zero_hit_prompts: int  # prompts with nothing expected in the top k


def summarise(name: str, scores: Sequence[PromptScore]) -> Summary:
    if not scores:
        raise ValueError(f"{name}: no prompts to summarise")
    n = len(scores)
    return Summary(
        name=name,
        prompts=n,
        mean_precision=round(sum(s.precision for s in scores) / n, 3),
        mean_normalised=round(sum(s.normalised for s in scores) / n, 3),
        mrr=round(sum(1 / s.first_hit_rank if s.first_hit_rank else 0 for s in scores) / n, 3),
        zero_hit_prompts=sum(1 for s in scores if s.hits == 0),
    )


def by_category(scores: Sequence[PromptScore]) -> dict[str, Summary]:
    """One Summary per category, in the order categories first appear."""
    order = list(dict.fromkeys(s.category for s in scores))
    return {c: summarise(c, [s for s in scores if s.category == c]) for c in order}


def weakest_categories(scores: Sequence[PromptScore]) -> list[Summary]:
    """Categories weakest first: lowest normalised P@k, then lowest MRR, then name.

    Normalised P@k leads so a category isn't called weak just because its
    prompts expect fewer titles.
    """
    return sorted(by_category(scores).values(),
                  key=lambda s: (s.mean_normalised, s.mrr, s.name))


IMPROVED, REGRESSED, UNCHANGED = "improved", "regressed", "unchanged"


@dataclass(frozen=True)
class PromptChange:
    """One prompt's score before and after a retrieval change."""

    before: PromptScore
    after: PromptScore

    @property
    def id(self) -> str:
        return self.after.id

    @property
    def category(self) -> str:
        return self.after.category

    @property
    def delta(self) -> float:
        return round(self.after.precision - self.before.precision, 3)

    @property
    def outcome(self) -> str:
        if self.delta > 0:
            return IMPROVED
        if self.delta < 0:
            return REGRESSED
        return UNCHANGED


def compare(before: Sequence[PromptScore], after: Sequence[PromptScore]) -> list[PromptChange]:
    """Pair two runs prompt by prompt. Both must score the same prompts in the same order."""
    if [s.id for s in before] != [s.id for s in after]:
        raise ValueError("before and after must score the same prompts in the same order")
    if any(b.k != a.k for b, a in zip(before, after)):
        raise ValueError("before and after must use the same k")
    return [PromptChange(b, a) for b, a in zip(before, after)]


def outcome_counts(changes: Sequence[PromptChange]) -> dict[str, int]:
    counts = {IMPROVED: 0, REGRESSED: 0, UNCHANGED: 0}
    for c in changes:
        counts[c.outcome] += 1
    return counts


def _distinct(titles: Sequence[str]) -> list[str]:
    """Titles in order with repeats dropped, so one game can't fill two slots."""
    seen: set[str] = set()
    out = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
