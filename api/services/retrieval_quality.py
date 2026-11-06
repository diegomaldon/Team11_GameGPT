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


def _distinct(titles: Sequence[str]) -> list[str]:
    """Titles in order with repeats dropped, so one game can't fill two slots."""
    seen: set[str] = set()
    out = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out
