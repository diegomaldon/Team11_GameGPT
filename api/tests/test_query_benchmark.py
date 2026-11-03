"""Tests for the TM11-63 retrieval benchmark fixture and its loader.

The first group checks the committed fixture against the acceptance criteria
(AC-01 20 prompts across the four categories, AC-02 expected titles that exist
in the catalogue). The second checks the loader rejects malformed files. No DB,
no network, no model.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from api.services.query_benchmark import (
    CATEGORIES,
    BenchmarkFormatError,
    BenchmarkQuery,
    load_query_benchmark,
)
from api.services.vector_store import NO_FILTERS

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "games.json"


@pytest.fixture(scope="module")
def benchmark() -> list[BenchmarkQuery]:
    return load_query_benchmark()


@pytest.fixture(scope="module")
def catalogue_titles() -> set[str]:
    return {g["title"] for g in json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))}


# ─────────────────────────── the committed fixture ───────────────────────────


def test_ac01_has_twenty_prompts(benchmark: list[BenchmarkQuery]) -> None:
    assert len(benchmark) == 20


def test_ac01_spans_genre_mood_comparison_and_platform(benchmark: list[BenchmarkQuery]) -> None:
    counts = Counter(q.category for q in benchmark)
    assert set(counts) == set(CATEGORIES)
    assert min(counts.values()) >= 3, counts


def test_ac01_platform_prompts_carry_a_platform_filter(benchmark: list[BenchmarkQuery]) -> None:
    for query in benchmark:
        if query.category == "platform":
            assert query.filters.platforms, query.id


def test_ac01_comparison_prompts_name_a_reference_game(benchmark: list[BenchmarkQuery]) -> None:
    for query in benchmark:
        if query.category == "comparison":
            assert query.reference_titles, query.id


def test_ac02_every_prompt_has_expected_titles(benchmark: list[BenchmarkQuery]) -> None:
    assert all(q.expected_titles for q in benchmark)


def test_ac02_expected_and_reference_titles_exist_in_catalogue(
    benchmark: list[BenchmarkQuery], catalogue_titles: set[str],
) -> None:
    missing = {
        q.id: [t for t in (*q.expected_titles, *q.reference_titles) if t not in catalogue_titles]
        for q in benchmark
    }
    assert not {qid: titles for qid, titles in missing.items() if titles}


def test_prompts_are_unique(benchmark: list[BenchmarkQuery]) -> None:
    prompts = [q.prompt.lower() for q in benchmark]
    assert len(set(prompts)) == len(prompts)


def test_prompts_fit_the_search_request_limit(benchmark: list[BenchmarkQuery]) -> None:
    # SemanticSearchRequest rejects queries over 500 characters with a 422.
    assert all(len(q.prompt) <= 500 for q in benchmark)


# ─────────────────────────── hit_rank ───────────────────────────


def test_hit_rank_is_position_of_first_expected_title() -> None:
    query = BenchmarkQuery(
        id="q", category="genre", prompt="p", filters=NO_FILTERS,
        expected_titles=("Celeste", "Hollow Knight"),
    )
    assert query.hit_rank(["Portal", "Hollow Knight", "Celeste"]) == 2


def test_hit_rank_ignores_reference_titles() -> None:
    query = BenchmarkQuery(
        id="q", category="comparison", prompt="like Hades", filters=NO_FILTERS,
        expected_titles=("Hades II",), reference_titles=("Hades",),
    )
    assert query.hit_rank(["Hades", "Celeste"]) is None


# ─────────────────────────── loader validation ───────────────────────────


def _entry(**overrides: object) -> dict:
    entry = {
        "id": "genre-01",
        "category": "genre",
        "prompt": "a platformer",
        "filters": {"platforms": [], "genres": []},
        "expected_titles": ["Celeste"],
    }
    entry.update(overrides)
    return entry


def _write(tmp_path: Path, *entries: dict) -> Path:
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps({"queries": list(entries)}), encoding="utf-8")
    return path


def test_loader_reads_filters_as_search_filters(tmp_path: Path) -> None:
    path = _write(tmp_path, _entry(filters={"platforms": ["xbox"], "genres": ["Survival"]}))
    (query,) = load_query_benchmark(path)
    assert query.filters.platforms == ("xbox",)
    assert query.filters.genres == ("Survival",)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"category": "vibes"}, "unknown category"),
        ({"prompt": "   "}, "blank prompt"),
        ({"expected_titles": []}, "at least one expected title"),
        ({"expected_titles": ["Celeste", ""]}, "non-blank titles"),
        ({"filters": {"platforms": ["playstation"]}}, "unknown platform"),
        ({"filters": []}, "filters must be an object"),
        ({"reference_titles": ["Celeste"]}, "both expected and a reference"),
    ],
)
def test_loader_rejects_a_malformed_query(
    tmp_path: Path, override: dict, message: str,
) -> None:
    with pytest.raises(BenchmarkFormatError, match=message):
        load_query_benchmark(_write(tmp_path, _entry(**override)))


def test_loader_names_missing_keys(tmp_path: Path) -> None:
    entry = _entry()
    del entry["expected_titles"]
    with pytest.raises(BenchmarkFormatError, match="genre-01: missing expected_titles"):
        load_query_benchmark(_write(tmp_path, entry))


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkFormatError, match="duplicate id"):
        load_query_benchmark(_write(tmp_path, _entry(), _entry(prompt="another")))


def test_loader_rejects_a_file_without_queries(tmp_path: Path) -> None:
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps({"queries": []}), encoding="utf-8")
    with pytest.raises(BenchmarkFormatError, match="non-empty 'queries' list"):
        load_query_benchmark(path)
