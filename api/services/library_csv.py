"""Parse and validate an uploaded library CSV (TM11-55, REQ004).

The text comes straight from a user's file, so nothing here trusts it. The
whole file is rejected (CsvFileError) when it can't be read as a library at
all: too big, not text, broken quoting, no "title" column. A single bad row is
only flagged (CsvRow.problem) so the rest of the file can still be imported.

Pure Python with no DB or network access. Matching and storage happen in
csv_import.py, so this stays easy to test on its own.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass

# Limits are on the decoded text, checked before any parsing. A library export
# of 2,000 titles is well under 100 KB, so these leave plenty of room.
MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 2_000
MAX_TITLE_LENGTH = 200

TITLE_COLUMN = "title"
APPID_COLUMN = "steam_appid"

# ASCII digits only: str.isdigit() also accepts digits from other scripts, and
# int() would silently convert them.
_APPID = re.compile(r"[0-9]{1,10}")
_MAX_APPID = 2_147_483_647  # owned_games.steam_appid is a Postgres integer

# The first row of a spreadsheet is the header, so data starts on row 2.
_FIRST_DATA_ROW = 2


class CsvFileError(Exception):
    """The file as a whole can't be used.

    `code` is stable for the UI to branch on. `user_message` is safe to show
    as is: it never repeats the file's contents.
    """

    def __init__(self, code: str, user_message: str) -> None:
        super().__init__(code)
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class CsvRow:
    """One data row. `problem` is set when this row can't be imported."""

    row_number: int  # as shown in a spreadsheet, so the user can find it
    title: str
    steam_appid: int | None = None
    problem: str | None = None


def parse_library_csv(text: str) -> list[CsvRow]:
    """Read a library CSV into rows, or raise CsvFileError."""
    _check_file(text)
    reader = csv.reader(io.StringIO(text.removeprefix("﻿")), strict=True)
    try:
        columns = _read_header(reader)
        rows = _read_rows(reader, columns)
    except csv.Error:
        raise CsvFileError(
            "malformed_csv",
            f"The file isn't valid CSV near line {reader.line_num}. "
            "Check for a missing closing quote.",
        ) from None
    if not rows:
        raise CsvFileError("no_rows", "The file has a header but no games.")
    return rows


def _check_file(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise CsvFileError(
            "file_too_large",
            f"The file is larger than {MAX_CSV_BYTES // 1_000_000} MB. "
            "Split it and upload each part.",
        )
    if "\x00" in text:
        raise CsvFileError("not_text", "This doesn't look like a CSV text file.")
    if not text.strip():
        raise CsvFileError("empty_file", "The file is empty.")


def _read_header(reader) -> dict[str, int]:
    """Map lower-cased column names to their position."""
    header = next(reader, [])
    names = [name.strip().lower() for name in header]
    if TITLE_COLUMN not in names:
        raise CsvFileError(
            "missing_title_column",
            'The first row must be a header with a "title" column, separated by commas.',
        )
    if len(set(names)) != len(names):
        raise CsvFileError("duplicate_column", "Two columns in the header have the same name.")
    return {name: position for position, name in enumerate(names)}


def _read_rows(reader, columns: dict[str, int]) -> list[CsvRow]:
    rows: list[CsvRow] = []
    for offset, cells in enumerate(reader):
        if not any(cell.strip() for cell in cells):
            continue  # blank line
        if len(rows) == MAX_CSV_ROWS:
            raise CsvFileError(
                "too_many_rows",
                f"The file has more than {MAX_CSV_ROWS:,} games. Split it and upload each part.",
            )
        rows.append(_to_row(_FIRST_DATA_ROW + offset, cells, columns))
    return rows


def _to_row(row_number: int, cells: list[str], columns: dict[str, int]) -> CsvRow:
    title = _cell(cells, columns.get(TITLE_COLUMN))
    appid_text = _cell(cells, columns.get(APPID_COLUMN))
    steam_appid = _parse_appid(appid_text)
    problem = _title_problem(title)
    if problem is None and appid_text and steam_appid is None:
        problem = "steam_appid must be a positive whole number."
    return CsvRow(row_number, title, steam_appid, problem)


def _cell(cells: list[str], position: int | None) -> str:
    """A trimmed cell, or "" when the column is missing or the row is short."""
    if position is None or position >= len(cells):
        return ""
    return cells[position].strip()


def _parse_appid(text: str) -> int | None:
    if not _APPID.fullmatch(text):
        return None
    appid = int(text)
    return appid if 0 < appid <= _MAX_APPID else None


def _title_problem(title: str) -> str | None:
    if not title:
        return "Title is empty."
    if len(title) > MAX_TITLE_LENGTH:
        return f"Title is longer than {MAX_TITLE_LENGTH} characters."
    if any(unicodedata.category(ch) == "Cc" for ch in title):
        return "Title contains control characters."
    return None
