"""Retrieval quality scoring against the TM11-63 benchmark (TM11-67).

Grouped by acceptance criterion. Result lists are written by hand, so these run
offline; scripts/eval_retrieval_quality.py scores the real model and catalogue
with the same functions.
"""

from __future__ import annotations

import pytest

from api.services.query_benchmark import BenchmarkQuery, load_query_benchmark
from api.services.retrieval_quality import (
    PRECISION_K,
    attainable_precision,
    precision_at,
    score_prompt,
)
from api.services.vector_store import NO_FILTERS


def query(expected, *, reference=(), category="genre", id="genre-01") -> BenchmarkQuery:
    return BenchmarkQuery(
        id=id, category=category, prompt="a prompt", filters=NO_FILTERS,
        expected_titles=tuple(expected), reference_titles=tuple(reference),
    )


FOUR = query(["A", "B", "C", "D"])


# ───────────────────── AC-01: precision at 5 per prompt ─────────────────────


def test_ac01_precision_is_measured_at_five_by_default():
    assert PRECISION_K == 5


@pytest.mark.parametrize("titles, expected", [
    (["A", "B", "C", "D", "x"], 0.8),
    (["A", "x", "B", "y", "z"], 0.4),
    (["x", "y", "z", "w", "v"], 0.0),
    (["x", "y", "z", "w", "v", "A"], 0.0),  # a hit at rank 6 is outside the top 5
])
def test_ac01_precision_counts_expected_titles_in_the_top_five(titles, expected):
    assert precision_at(FOUR, titles) == pytest.approx(expected)


def test_ac01_a_short_list_still_divides_by_k():
    assert precision_at(FOUR, ["A"]) == pytest.approx(0.2)
    assert precision_at(FOUR, []) == 0.0


def test_ac01_a_repeated_title_fills_one_slot_not_two():
    assert precision_at(FOUR, ["A", "A", "A", "B", "C"]) == pytest.approx(0.6)


def test_ac01_a_reference_title_is_never_a_hit():
    q = query(["Dinkum"], reference=["Stardew Valley"], category="comparison", id="comparison-01")
    assert precision_at(q, ["Stardew Valley", "x", "y", "z", "w"]) == 0.0


def test_ac01_attainable_precision_is_capped_by_the_expected_set():
    assert attainable_precision(FOUR) == pytest.approx(0.8)
    assert attainable_precision(query(list("ABCDEFG"))) == pytest.approx(1.0)
    assert attainable_precision(query(["A"])) == pytest.approx(0.2)


def test_ac01_normalised_precision_is_against_what_the_prompt_allows():
    perfect = score_prompt(FOUR, ["A", "B", "C", "D", "x"])
    assert perfect.precision == pytest.approx(0.8)
    assert perfect.normalised == pytest.approx(1.0)
    half = score_prompt(FOUR, ["A", "x", "B", "y", "z"])
    assert half.normalised == pytest.approx(0.5)


def test_ac01_a_prompt_score_records_what_the_report_needs():
    s = score_prompt(FOUR, ["x", "B", "y", "C", "z", "A"])
    assert (s.id, s.category, s.k, s.hits) == ("genre-01", "genre", 5, 2)
    assert s.first_hit_rank == 2
    assert s.top_k == ("x", "B", "y", "C", "z")


def test_ac01_first_hit_rank_looks_past_the_top_five():
    assert score_prompt(FOUR, ["x", "y", "z", "w", "v", "D"]).first_hit_rank == 6
    assert score_prompt(FOUR, ["x"]).first_hit_rank is None


@pytest.mark.parametrize("k", [0, -1])
def test_ac01_k_must_be_positive(k):
    with pytest.raises(ValueError):
        precision_at(FOUR, ["A"], k=k)
    with pytest.raises(ValueError):
        attainable_precision(FOUR, k=k)


def test_ac01_every_benchmark_prompt_can_be_scored():
    benchmark = load_query_benchmark()
    scores = [score_prompt(q, list(q.expected_titles)) for q in benchmark]
    assert len(scores) == 20
    # Handing back the expected titles is the best possible list for each prompt.
    assert all(s.normalised == pytest.approx(1.0) for s in scores)
