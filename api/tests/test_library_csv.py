"""Parsing and validating an uploaded library CSV (TM11-55, REQ004).

The file comes from a user, so every test here is about refusing bad input
cleanly: the whole file when it is unusable, a single row when only that row
is wrong.
"""

from __future__ import annotations

import pytest

from api.services.library_csv import (
    MAX_CSV_BYTES,
    MAX_CSV_ROWS,
    MAX_TITLE_LENGTH,
    CsvFileError,
    parse_library_csv,
)


def _error_code(text: str) -> str:
    with pytest.raises(CsvFileError) as exc:
        parse_library_csv(text)
    return exc.value.code


# ───────────────────────── a good file ─────────────────────────


def test_reads_titles_and_optional_appids():
    rows = parse_library_csv("title,steam_appid\nHades,1145360\nCeleste,\n")
    assert [(r.row_number, r.title, r.steam_appid, r.problem) for r in rows] == [
        (2, "Hades", 1145360, None),
        (3, "Celeste", None, None),
    ]


def test_appid_column_is_optional():
    rows = parse_library_csv("title\nHades\n")
    assert rows[0].steam_appid is None


def test_header_is_case_and_space_insensitive_and_extra_columns_are_ignored():
    rows = parse_library_csv(" Title , Notes \nHades,loved it\n")
    assert rows[0].title == "Hades"


def test_quoted_titles_with_commas_survive():
    rows = parse_library_csv('title\n"Papers, Please"\n')
    assert rows[0].title == "Papers, Please"


def test_excel_byte_order_mark_is_ignored():
    rows = parse_library_csv("﻿title\nHades\n")
    assert rows[0].title == "Hades"


def test_windows_line_endings_work():
    rows = parse_library_csv("title\r\nHades\r\nCeleste\r\n")
    assert [r.title for r in rows] == ["Hades", "Celeste"]


def test_blank_lines_are_skipped_but_row_numbers_match_the_spreadsheet():
    rows = parse_library_csv("title\nHades\n\nCeleste\n")
    assert [(r.row_number, r.title) for r in rows] == [(2, "Hades"), (4, "Celeste")]


def test_surrounding_whitespace_is_trimmed():
    rows = parse_library_csv("title\n   Hades   \n")
    assert rows[0].title == "Hades"


# ───────────── AC: malformed file rejected with a useful message ─────────────


def test_empty_file_is_rejected():
    assert _error_code("") == "empty_file"
    assert _error_code("  \n\n ") == "empty_file"


def test_file_without_a_title_column_is_rejected():
    assert _error_code("name,appid\nHades,1\n") == "missing_title_column"


def test_semicolon_separated_file_explains_commas():
    with pytest.raises(CsvFileError) as exc:
        parse_library_csv("title;steam_appid\nHades;1145360\n")
    assert exc.value.code == "missing_title_column"
    assert "comma" in exc.value.user_message


def test_duplicate_column_names_are_rejected():
    assert _error_code("title,title\nHades,Celeste\n") == "duplicate_column"


def test_header_only_file_is_rejected():
    assert _error_code("title\n") == "no_rows"
    assert _error_code("title\n,\n\n") == "no_rows"


def test_binary_file_is_rejected():
    assert _error_code("title\nHad\x00es\n") == "not_text"


def test_broken_quoting_is_rejected_with_the_line():
    with pytest.raises(CsvFileError) as exc:
        parse_library_csv('title\n"Hades\n')
    assert exc.value.code == "malformed_csv"
    assert "line" in exc.value.user_message


def test_file_over_the_size_limit_is_rejected():
    text = "title\n" + "x" * MAX_CSV_BYTES
    assert _error_code(text) == "file_too_large"


def test_size_limit_counts_bytes_not_characters():
    # Each "é" is two bytes in UTF-8, so this is over the limit in bytes.
    text = "title\n" + "é" * (MAX_CSV_BYTES // 2 + 1)
    assert _error_code(text) == "file_too_large"


def test_file_over_the_row_limit_is_rejected():
    text = "title\n" + "\n".join(f"Game {i}" for i in range(MAX_CSV_ROWS + 1))
    assert _error_code(text) == "too_many_rows"


def test_file_at_the_row_limit_is_accepted():
    text = "title\n" + "\n".join(f"Game {i}" for i in range(MAX_CSV_ROWS))
    assert len(parse_library_csv(text)) == MAX_CSV_ROWS


def test_error_messages_never_echo_the_file_back():
    """The message is shown to the user and logged; file contents stay out of both."""
    with pytest.raises(CsvFileError) as exc:
        parse_library_csv("secret-column\nprivate-value\n")
    assert "secret" not in exc.value.user_message
    assert "private" not in exc.value.user_message


# ─────────────── a bad row is reported, the rest of the file stays ───────────────


def test_blank_title_is_a_row_problem_not_a_file_error():
    rows = parse_library_csv("title,steam_appid\n,620\nHades,\n")
    assert rows[0].problem == "Title is empty."
    assert rows[1].problem is None


def test_overlong_title_is_a_row_problem():
    rows = parse_library_csv("title\n" + "x" * (MAX_TITLE_LENGTH + 1) + "\n")
    assert rows[0].problem == f"Title is longer than {MAX_TITLE_LENGTH} characters."


def test_title_at_the_length_limit_is_fine():
    rows = parse_library_csv("title\n" + "x" * MAX_TITLE_LENGTH + "\n")
    assert rows[0].problem is None


def test_control_characters_in_a_title_are_a_row_problem():
    rows = parse_library_csv('title\n"Ha\x1bdes"\n')
    assert rows[0].problem == "Title contains control characters."


@pytest.mark.parametrize("appid", ["abc", "1.5", "-3", "0", "99999999999", "1e3", "١٢"])
def test_appid_must_be_a_positive_whole_number(appid):
    rows = parse_library_csv(f"title,steam_appid\nHades,{appid}\n")
    assert rows[0].problem == "steam_appid must be a positive whole number."
    assert rows[0].steam_appid is None


def test_short_row_is_read_as_empty_cells():
    rows = parse_library_csv("steam_appid,title\n620\n")
    assert rows[0].problem == "Title is empty."
