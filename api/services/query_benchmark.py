"""Load the retrieval benchmark: 20 prompts with their expected-good titles (TM11-63).

The prompts live in api/fixtures/query_benchmark.json so every evaluation
scores the same questions: the TM11-40 index check, the TM11-42 latency run and
the TM11-67 quality evaluation. Changing a prompt changes every number measured
against it, so the file is versioned and checked here instead of trusted.

Not a SysML block: test data plus the loader that reads it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from api.models.schemas import SearchPlatform
from api.services.vector_store import SearchFilters

BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "query_benchmark.json"
CATEGORIES = ("genre", "mood", "comparison", "platform")
PLATFORMS = frozenset(get_args(SearchPlatform))
REQUIRED_KEYS = ("id", "category", "prompt", "filters", "expected_titles")


class BenchmarkFormatError(ValueError):
    """The benchmark file is malformed. The message names the query at fault."""


@dataclass(frozen=True)
class BenchmarkQuery:
    id: str
    category: str
    prompt: str
    filters: SearchFilters
    expected_titles: tuple[str, ...]
    # Games the prompt names ("like Stardew Valley"). Returning one is not a hit.
    reference_titles: tuple[str, ...] = ()
    note: str = ""

    def hit_rank(self, titles: list[str]) -> int | None:
        """1-based position of the first expected title in `titles`, or None."""
        expected = set(self.expected_titles)
        return next((rank for rank, t in enumerate(titles, start=1) if t in expected), None)


def load_query_benchmark(path: Path = BENCHMARK_PATH) -> list[BenchmarkQuery]:
    """Read and validate the benchmark, in file order."""
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    entries = raw.get("queries") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise BenchmarkFormatError(f"{path.name}: expected a non-empty 'queries' list")

    queries = [_parse_query(entry, index) for index, entry in enumerate(entries)]
    seen_ids: set[str] = set()
    for query in queries:
        if query.id in seen_ids:
            raise BenchmarkFormatError(f"{query.id}: duplicate id")
        seen_ids.add(query.id)
    return queries


def _parse_query(entry: Any, index: int) -> BenchmarkQuery:
    label = entry.get("id", f"queries[{index}]") if isinstance(entry, dict) else f"queries[{index}]"
    if not isinstance(entry, dict):
        raise BenchmarkFormatError(f"{label}: expected an object")
    missing = [key for key in REQUIRED_KEYS if key not in entry]
    if missing:
        raise BenchmarkFormatError(f"{label}: missing {', '.join(missing)}")

    if entry["category"] not in CATEGORIES:
        raise BenchmarkFormatError(f"{label}: unknown category {entry['category']!r}")
    prompt = str(entry["prompt"]).strip()
    if not prompt:
        raise BenchmarkFormatError(f"{label}: blank prompt")

    expected = _titles(entry["expected_titles"], label, "expected_titles")
    if not expected:
        raise BenchmarkFormatError(f"{label}: needs at least one expected title")
    reference = _titles(entry.get("reference_titles", []), label, "reference_titles")
    overlap = set(expected) & set(reference)
    if overlap:
        raise BenchmarkFormatError(
            f"{label}: {', '.join(sorted(overlap))} is both expected and a reference title"
        )

    return BenchmarkQuery(
        id=label,
        category=entry["category"],
        prompt=prompt,
        filters=_filters(entry["filters"], label),
        expected_titles=expected,
        reference_titles=reference,
        note=str(entry.get("note", "")),
    )


def _titles(value: Any, label: str, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(t, str) and t.strip() for t in value):
        raise BenchmarkFormatError(f"{label}: {field} must be a list of non-blank titles")
    return tuple(value)


def _filters(value: Any, label: str) -> SearchFilters:
    if not isinstance(value, dict):
        raise BenchmarkFormatError(f"{label}: filters must be an object")
    platforms = value.get("platforms", [])
    genres = value.get("genres", [])
    unknown = [p for p in platforms if p not in PLATFORMS]
    if unknown:
        raise BenchmarkFormatError(f"{label}: unknown platform {', '.join(map(repr, unknown))}")
    return SearchFilters(platforms=tuple(platforms), genres=tuple(genres))
