"""Turns `recommend.timings` log lines into a p50/p95 table per stage. TM11-68 · REQ040.

The weekly latency check (scripts/latency_report.py) and the local benchmark
(scripts/eval_recommend_latency.py) both report through here, so the budget doc and
the weekly numbers are worked out the same way. Failed requests are counted by the
stage that failed and left out of the percentiles: a request that died early would
make the stages after it look fast.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from api.observability.stage_timings import (
    STAGE_BUDGET_MS,
    STAGES,
    TIMING_LOG_MESSAGE,
    TOTAL_BUDGET_MS,
)

REPORTED = (*STAGES, "total")
BUDGET_MS = {**STAGE_BUDGET_MS, "total": TOTAL_BUDGET_MS}


@dataclass(frozen=True)
class StageSummary:
    stage: str
    budget_ms: float
    p50_ms: float | None
    p95_ms: float | None
    runs: int

    @property
    def is_within_budget(self) -> bool | None:
        """p95 under budget. None when the stage has no timings to judge."""
        return None if self.p95_ms is None else self.p95_ms <= self.budget_ms


@dataclass(frozen=True)
class LatencyReport:
    stages: tuple[StageSummary, ...]
    runs: int
    failures: dict[str, int]

    @property
    def is_within_budget(self) -> bool:
        return all(s.is_within_budget is not False for s in self.stages)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile, so p95 of 100 runs is the 95th slowest.

    The rank rounds up: p95 of 30 runs is the 29th, not the 28th.
    """
    ordered = sorted(values)
    rank = max(1, math.ceil(pct * len(ordered) / 100))
    return ordered[rank - 1]


def read_timing_lines(lines: Iterable[str]) -> list[dict]:
    """The `recommend.timings` entries among log lines. Anything else is skipped."""
    entries = []
    for line in lines:
        start = line.find("{")  # Render prints a timestamp before each JSON line
        if start == -1:
            continue
        try:
            entry = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("msg") == TIMING_LOG_MESSAGE:
            entries.append(entry)
    return entries


def summarise(entries: list[dict]) -> LatencyReport:
    finished = [e for e in entries if not e.get("failed_stage")]
    failures = Counter(e["failed_stage"] for e in entries if e.get("failed_stage"))
    return LatencyReport(
        stages=tuple(_summarise_stage(stage, finished) for stage in REPORTED),
        runs=len(finished),
        failures=dict(failures),
    )


def _summarise_stage(stage: str, entries: list[dict]) -> StageSummary:
    values = [e[f"{stage}_ms"] for e in entries if isinstance(e.get(f"{stage}_ms"), (int, float))]
    return StageSummary(
        stage=stage,
        budget_ms=BUDGET_MS[stage],
        p50_ms=percentile(values, 50) if values else None,
        p95_ms=percentile(values, 95) if values else None,
        runs=len(values),
    )


def to_markdown(report: LatencyReport, *, title: str) -> str:
    rows = [
        f"| {s.stage} | {_ms(s.p50_ms)} | {_ms(s.p95_ms)} | {_ms(s.budget_ms)} | "
        f"{_verdict(s.is_within_budget)} |"
        for s in report.stages
    ]
    failures = ", ".join(f"{stage} {count}" for stage, count in report.failures.items())
    return "\n".join([
        f"# {title}",
        "",
        f"{report.runs} finished requests. Failed: {failures or 'none'}.",
        "",
        "| Stage | p50 | p95 | p95 budget | Within budget |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ])


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.1f} ms"


def _verdict(is_within_budget: bool | None) -> str:
    if is_within_budget is None:
        return "n/a"
    return "yes" if is_within_budget else "**no**"
