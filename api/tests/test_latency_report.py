"""The weekly recommend latency report, read from the API's JSON log lines.

TM11-68 (REQ040). Offline: the log lines are written by the tests.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from api.observability.latency_report import (
    percentile,
    read_timing_lines,
    summarise,
    to_markdown,
)
from api.observability.stage_timings import STAGE_BUDGET_MS, STAGES

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "latency_report.py"


def load_script():
    spec = importlib.util.spec_from_file_location("latency_report_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timing_line(*, rank_ms: float = 2000.0, failed_stage: str | None = None, **extra) -> str:
    fields = {"parse_ms": 2.0, "embed_ms": 30.0, "retrieve_ms": 60.0, "filter_ms": 8.0,
              "rank_ms": rank_ms}
    fields["total_ms"] = sum(fields.values())
    return json.dumps({"level": "info", "logger": "gamegpt.latency", "msg": "recommend.timings",
                       "request_id": "abc", **fields, "failed_stage": failed_stage, **extra})


def stage(report, name):
    return next(s for s in report.stages if s.stage == name)


def test_percentiles_are_nearest_rank():
    values = list(range(1, 101))

    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([7.0], 95) == 7.0


def test_nearest_rank_rounds_up_never_to_a_faster_rank():
    # 95% of 30 is rank 28.5, so p95 is the 29th value. Rounding down to 28 would let a
    # stage just over budget pass.
    assert percentile(list(range(1, 31)), 95) == 29
    assert percentile(list(range(1, 6)), 50) == 3


def test_only_recommend_timing_lines_are_read():
    lines = [
        timing_line(),
        json.dumps({"msg": "request.complete", "duration_ms": 900}),
        "not json at all",
        "",
        # Render puts a timestamp in front of each line it shows.
        "2026-11-05T14:03:11.204Z " + timing_line(),
    ]

    assert len(read_timing_lines(lines)) == 2


def test_each_stage_gets_a_p50_and_p95():
    lines = [timing_line(rank_ms=ms) for ms in range(1000, 1100)]

    report = summarise(read_timing_lines(lines))

    rank = stage(report, "rank")
    assert (rank.p50_ms, rank.p95_ms, rank.runs) == (1049, 1094, 100)
    assert [s.stage for s in report.stages] == [*STAGES, "total"]


def test_failed_runs_are_counted_by_stage_and_left_out_of_the_percentiles():
    lines = [timing_line(rank_ms=1000)] * 3 + [timing_line(rank_ms=30_000, failed_stage="rank")]

    report = summarise(read_timing_lines(lines))

    assert report.runs == 3
    assert report.failures == {"rank": 1}
    assert stage(report, "rank").p95_ms == 1000


def test_a_stage_slower_than_its_budget_at_p95_is_flagged():
    too_slow = STAGE_BUDGET_MS["rank"] + 1
    report = summarise(read_timing_lines([timing_line(rank_ms=too_slow)] * 20))

    assert stage(report, "rank").is_within_budget is False
    assert stage(report, "parse").is_within_budget is True
    assert report.is_within_budget is False


def test_the_markdown_table_shows_each_stage_against_its_budget():
    markdown = to_markdown(summarise(read_timing_lines([timing_line()] * 5)), title="Week 1")

    assert markdown.startswith("# Week 1")
    assert "| rank | 2000.0 ms | 2000.0 ms |" in markdown
    assert "| total |" in markdown


def test_the_script_exits_0_within_budget_and_1_over_it(tmp_path, capsys):
    script = load_script()
    within, over = tmp_path / "within.log", tmp_path / "over.log"
    within.write_text("\n".join([timing_line()] * 5))
    over.write_text("\n".join([timing_line(rank_ms=60_000)] * 5))

    assert script.main([str(within)]) == 0
    assert script.main([str(over)]) == 1
    assert "| rank |" in capsys.readouterr().out


def test_the_script_exits_2_when_there_is_nothing_to_report(tmp_path, capsys):
    empty = tmp_path / "empty.log"
    empty.write_text(json.dumps({"msg": "request.complete"}) + "\n")

    assert load_script().main([str(empty)]) == 2
    assert "no recommend.timings lines" in capsys.readouterr().err
