"""CsvImportService: preview a library CSV, then commit what the user kept (TM11-55).

The DB layer is faked, so this runs offline with no DATABASE_URL.
"""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

import pytest

from api.db import repositories
from api.models import CsvRowStatus
from api.models.schemas import _MAX_CSV_ROWS, _MAX_CSV_TEXT
from api.services.csv_import import CsvImportService, CsvReviewMismatchError
from api.services.library_csv import MAX_CSV_BYTES, MAX_CSV_ROWS, CsvFileError

pytestmark = pytest.mark.asyncio

USER = UUID("00000000-0000-0000-0000-000000000001")
HADES, CELESTE, DOOM, DOOM_2016, HALO = (uuid4() for _ in range(5))

CATALOGUE = [
    {"game_id": HADES, "title": "Hades", "steam_appid": 1145360},
    {"game_id": CELESTE, "title": "Celeste", "steam_appid": None},
    {"game_id": DOOM, "title": "DOOM", "steam_appid": None},
    {"game_id": DOOM_2016, "title": "Doom", "steam_appid": None},  # same normalised title
    {"game_id": HALO, "title": "Halo Infinite", "steam_appid": None},
]


@pytest.fixture
def fake_db(monkeypatch):
    db: dict = {"owned": set(), "added": [], "reports": [], "fail_report": False}

    async def list_catalogue_games():
        return CATALOGUE

    async def list_owned_game_ids(user_id, platform):
        db["owned_lookup"] = (user_id, platform)
        return set(db["owned"])

    async def add_owned_games(user_id, platform, games):
        db["added"].append((user_id, platform, list(games)))
        new = [g for g, _ in games if g not in db["owned"]]
        db["owned"].update(new)
        return len(new)

    async def record_library_import(user_id, platform, source, report):
        if db["fail_report"]:
            raise RuntimeError("db hiccup")
        db["reports"].append((user_id, platform, source, report))
        return uuid4()

    monkeypatch.setattr(repositories, "list_catalogue_games", list_catalogue_games)
    monkeypatch.setattr(repositories, "list_owned_game_ids", list_owned_game_ids)
    monkeypatch.setattr(repositories, "add_owned_games", add_owned_games)
    monkeypatch.setattr(repositories, "record_library_import", record_library_import)
    return db


def _by_title(preview):
    return {row.title: row for row in preview.rows}


# ──────────── AC: CSV upload parsed with per-row match results ────────────


async def test_every_row_gets_a_status(fake_db):
    fake_db["owned"].add(HALO)
    csv_text = (
        "title,steam_appid\n"
        "Hades,1145360\n"       # matched by appid
        "Celeste,\n"            # matched by title
        "doom,\n"               # two catalogue games normalise to "doom"
        "Not A Real Game,\n"    # nothing in the catalogue
        ",620\n"                # blank title
        "Hades,\n"              # same game as row 2
        "Halo Infinite,\n"      # already in the library
    )
    rows = (await CsvImportService().preview(USER, "epic", csv_text)).rows
    assert [(r.row_number, r.status) for r in rows] == [
        (2, CsvRowStatus.matched),
        (3, CsvRowStatus.matched),
        (4, CsvRowStatus.ambiguous),
        (5, CsvRowStatus.unmatched),
        (6, CsvRowStatus.invalid),
        (7, CsvRowStatus.duplicate),
        (8, CsvRowStatus.already_owned),
    ]


async def test_matched_rows_name_the_catalogue_game(fake_db):
    preview = await CsvImportService().preview(USER, "epic", "title\ncelESTE\n")
    row = preview.rows[0]
    assert (row.game_id, row.game_title, row.message) == (CELESTE, "Celeste", None)


async def test_ambiguous_rows_list_the_candidates(fake_db):
    preview = await CsvImportService().preview(USER, "epic", "title\ndoom\n")
    assert "DOOM" in preview.rows[0].message and "Doom" in preview.rows[0].message
    assert preview.rows[0].game_id is None


async def test_invalid_rows_carry_the_reason(fake_db):
    preview = await CsvImportService().preview(USER, "epic", "title,steam_appid\nHades,abc\n")
    assert preview.rows[0].status is CsvRowStatus.invalid
    assert preview.rows[0].message == "steam_appid must be a positive whole number."


async def test_duplicates_of_unmatched_titles_are_caught_too(fake_db):
    preview = await CsvImportService().preview(USER, "epic", "title\nMystery\nmystery!\n")
    assert [r.status for r in preview.rows] == [CsvRowStatus.unmatched, CsvRowStatus.duplicate]


async def test_preview_counts_add_up(fake_db):
    fake_db["owned"].add(HALO)
    preview = await CsvImportService().preview(
        USER, "epic", "title\nHades\ndoom\nNope\nHalo Infinite\n"
    )
    assert (preview.matched, preview.needs_review, preview.skipped) == (1, 2, 1)
    assert preview.platform == "epic"


async def test_already_owned_is_checked_on_the_chosen_platform(fake_db):
    await CsvImportService().preview(USER, "xbox", "title\nHades\n")
    assert fake_db["owned_lookup"] == (USER, "xbox")


# ──────────── AC: review step before anything is committed ────────────


async def test_preview_writes_nothing(fake_db):
    await CsvImportService().preview(USER, "epic", "title\nHades\nNope\n")
    assert fake_db["added"] == []
    assert fake_db["reports"] == []


async def test_commit_adds_only_the_matched_rows(fake_db):
    result = await CsvImportService().commit(
        USER, "epic", "title\nHades\nCeleste\nNope\n", excluded_rows=[]
    )
    assert fake_db["added"] == [(USER, "epic", [(HADES, "Hades"), (CELESTE, "Celeste")])]
    assert (result.added, result.needs_review, result.skipped) == (2, 1, 0)


async def test_unticked_rows_are_left_out(fake_db):
    result = await CsvImportService().commit(
        USER, "epic", "title\nHades\nCeleste\n", excluded_rows=[3]
    )
    assert fake_db["added"][0][2] == [(HADES, "Hades")]
    assert result.skipped == 1


async def test_commit_rejects_row_numbers_the_file_does_not_have(fake_db):
    """A tampered or stale review must not be guessed at; nothing is written."""
    with pytest.raises(CsvReviewMismatchError):
        await CsvImportService().commit(USER, "epic", "title\nHades\n", excluded_rows=[99])
    assert fake_db["added"] == []


async def test_commit_rechecks_the_file_instead_of_trusting_the_preview(fake_db):
    """The commit re-validates the same text, so a bad file can't be committed."""
    with pytest.raises(CsvFileError):
        await CsvImportService().commit(USER, "epic", "name\nHades\n", excluded_rows=[])
    assert fake_db["added"] == []


async def test_a_game_added_since_the_preview_is_not_added_twice(fake_db):
    service = CsvImportService()
    await service.commit(USER, "epic", "title\nHades\n", excluded_rows=[])
    second = await service.commit(USER, "epic", "title\nHades\n", excluded_rows=[])
    assert second.added == 0
    assert second.skipped == 1


async def test_nothing_to_add_still_records_the_report(fake_db):
    result = await CsvImportService().commit(USER, "epic", "title\nNope\n", excluded_rows=[])
    assert result.added == 0
    assert len(fake_db["reports"]) == 1


# ──────────── AC: unmatched rows reported back to the user ────────────


async def test_unmatched_and_ambiguous_rows_go_to_the_review_queue(fake_db):
    await CsvImportService().commit(USER, "epic", "title\nHades\ndoom\nNope\n", excluded_rows=[])
    user_id, platform, source, report = fake_db["reports"][0]
    assert (user_id, platform, source) == (USER, "epic", "csv")
    assert [m.game_id for m in report.matched] == [HADES]
    assert sorted(u.reason for u in report.unmatched) == ["ambiguous", "no_match"]


async def test_unticked_unmatched_rows_are_not_queued(fake_db):
    await CsvImportService().commit(USER, "epic", "title\nHades\nNope\n", excluded_rows=[3])
    assert fake_db["reports"][0][3].unmatched == []


async def test_a_failed_report_does_not_undo_a_good_import(fake_db):
    fake_db["fail_report"] = True
    result = await CsvImportService().commit(USER, "epic", "title\nHades\n", excluded_rows=[])
    assert result.added == 1
    assert result.import_id is None


# ──────────── privacy and limits ────────────


async def test_titles_never_reach_the_logs(fake_db, caplog):
    """A library is personal data: log counts, never the file's contents."""
    with caplog.at_level(logging.DEBUG):
        await CsvImportService().commit(
            USER, "epic", "title\nHades\nMy Secret Game\n", excluded_rows=[]
        )
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "Hades" not in text and "Secret" not in text


async def test_request_limits_match_the_parser():
    assert _MAX_CSV_TEXT == MAX_CSV_BYTES
    assert _MAX_CSV_ROWS == MAX_CSV_ROWS
