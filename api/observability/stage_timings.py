"""Times each stage of a recommendation. TM11-68 · REQ040.

REQ040 gives POST /api/recommend 10 seconds. The pipeline runs five stages in a row
(parse, embed, retrieve, filter, rank); this records how long each one took, so a slow
answer can be pinned on the stage that caused it. RAGPipeline logs the result as one
`recommend.timings` line per request, success or failure, and the router sends the
same numbers back as a Server-Timing header. docs/OBSERVABILITY.md has the budgets
and how the team reads the numbers each week.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

STAGES = ("parse", "embed", "retrieve", "filter", "rank")

TOTAL_BUDGET_MS = 10_000  # REQ040
# Each stage's p95 budget. Embed plus retrieve is TM11-42's 1 second search budget,
# filter opens its own database connection, and the 750 ms left over covers the
# HTTP layer around the pipeline. docs/OBSERVABILITY.md explains each number.
STAGE_BUDGET_MS = {
    "parse": 250,
    "embed": 250,
    "retrieve": 750,
    "filter": 500,
    "rank": 7500,
}

TIMING_LOG_MESSAGE = "recommend.timings"
SERVER_TIMING_HEADER = "Server-Timing"


class StageTimings:
    """Records how long each pipeline stage takes, in milliseconds."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter) -> None:
        self._clock = clock
        self._durations_ms: dict[str, float] = {}
        self.failed_stage: str | None = None

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time the block as stage `name`. If it raises, the stage is still timed.

        Timing the same stage twice adds the two up: when the user owns most of the
        first candidates, the pipeline retrieves and filters again (TM11-66).
        """
        if name not in STAGES:
            raise ValueError(f"unknown pipeline stage {name!r}; expected one of {STAGES}")
        started = self._clock()
        try:
            yield
        except BaseException:
            # BaseException too: a client that hangs up cancels the request mid-stage,
            # and that request didn't finish either.
            self.failed_stage = name
            raise
        finally:
            elapsed_ms = (self._clock() - started) * 1000
            self._durations_ms[name] = self._durations_ms.get(name, 0.0) + elapsed_ms

    def total_ms(self) -> float:
        # The stages run one after another, so their sum is the pipeline's run time.
        return sum(self._durations_ms.values())

    def log_fields(self) -> dict[str, float | str | None]:
        """Fields for the timing log line. Every stage is present, null if it never ran."""
        fields: dict[str, float | str | None] = {
            f"{stage}_ms": _rounded(self._durations_ms.get(stage)) for stage in STAGES
        }
        fields["total_ms"] = _rounded(self.total_ms())
        fields["failed_stage"] = self.failed_stage
        return fields

    def server_timing(self) -> str:
        """The stages that ran, as a Server-Timing header value."""
        parts = [
            f"{stage};dur={_rounded(self._durations_ms[stage])}"
            for stage in STAGES
            if stage in self._durations_ms
        ]
        parts.append(f"total;dur={_rounded(self.total_ms())}")
        return ", ".join(parts)


def _rounded(ms: float | None) -> float | None:
    return None if ms is None else round(ms, 1)
