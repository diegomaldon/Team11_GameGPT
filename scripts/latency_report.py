"""Weekly recommend latency check: p50 and p95 per stage from the API logs. TM11-68.

Reads the JSON log lines the API writes (one `recommend.timings` line per
POST /api/recommend) and prints each stage's p50 and p95 against its budget.
Download the logs from the Render dashboard, or pipe them in.

Usage (from the repo root, venv active):
    python scripts/latency_report.py render-logs.txt
    pbpaste | python scripts/latency_report.py -

Exits 0 when every stage's p95 is within budget, 1 when one is over, and 2 when
there are no timing lines to read.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.observability.latency_report import (  # noqa: E402
    read_timing_lines,
    summarise,
    to_markdown,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log_file", help="file of API log lines, or - for stdin")
    args = parser.parse_args(argv)

    if args.log_file == "-":
        entries = read_timing_lines(sys.stdin)
    else:
        with open(args.log_file, encoding="utf-8") as f:
            entries = read_timing_lines(f)

    if not entries:
        print("no recommend.timings lines in the input", file=sys.stderr)
        return 2

    report = summarise(entries)
    print(to_markdown(report, title="Recommend latency by stage"))
    return 0 if report.is_within_budget else 1


if __name__ == "__main__":
    sys.exit(main())
