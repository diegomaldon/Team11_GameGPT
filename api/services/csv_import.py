"""CsvImportService: preview a library CSV, then commit what the user kept.

TM11-55, the second half of REQ004 (platforms with no library API).

  preview  parse the file, match each row against the games catalogue, and
           flag duplicates and games already owned. Writes nothing.
  commit   run the same review again on the same text, then add the matched
           rows the user didn't untick. Unmatched and ambiguous rows go to the
           review queue (unmatched_import_titles) instead of being dropped.

Commit re-checks the file rather than trusting what the browser saw. The
client can only leave rows out; it can't add a row the preview wouldn't have
added, or name its own game ids.

Logs carry counts only. A library is personal data, so titles stay out.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from api.db import repositories
from api.models import CsvCommitResponse, CsvPreviewResponse, CsvRowResult, CsvRowStatus
from api.services.library_csv import CsvRow, parse_library_csv
from api.services.title_matching import (
    ImportedTitle,
    MatchReport,
    TitleMatch,
    TitleMatcher,
    UnmatchedTitle,
    catalogue_from_rows,
)

log = logging.getLogger("gamegpt.csv_import")

CSV_SOURCE = "csv"  # library_imports.source for these uploads

_NEEDS_REVIEW = (CsvRowStatus.ambiguous, CsvRowStatus.unmatched)
_MAX_CANDIDATES_SHOWN = 5


class CsvReviewMismatchError(Exception):
    """The commit names rows the file doesn't have: stale or tampered review."""

    code = "review_mismatch"
    user_message = "The review no longer matches the file. Upload it again."


@dataclass(frozen=True)
class _ReviewedRow:
    row: CsvRow
    status: CsvRowStatus
    match: TitleMatch | UnmatchedTitle | None = None
    game_title: str | None = None
    message: str | None = None


class CsvImportService:
    async def preview(self, user_id: UUID, platform: str, csv_text: str) -> CsvPreviewResponse:
        """Per-row results for the file. Raises CsvFileError for an unusable file."""
        reviewed = await _review(user_id, platform, csv_text)
        statuses = [r.status for r in reviewed]
        matched_count = statuses.count(CsvRowStatus.matched)
        needs_review_count = sum(statuses.count(s) for s in _NEEDS_REVIEW)
        log.info(
            "csv preview: user=%s platform=%s rows=%d matched=%d needs_review=%d",
            user_id, platform, len(reviewed), matched_count, needs_review_count,
        )
        return CsvPreviewResponse(
            platform=platform,
            rows=[_to_result(r) for r in reviewed],
            matched=matched_count,
            needs_review=needs_review_count,
            skipped=len(reviewed) - matched_count - needs_review_count,
        )

    async def commit(
        self,
        user_id: UUID,
        platform: str,
        csv_text: str,
        *,
        excluded_rows: Collection[int],
    ) -> CsvCommitResponse:
        """Add the matched rows the user kept and queue the rest for review.

        Raises CsvFileError for an unusable file and CsvReviewMismatchError
        when `excluded_rows` names a row the file doesn't have. Nothing is
        written in either case.
        """
        reviewed = await _review(user_id, platform, csv_text)
        excluded = set(excluded_rows)
        if not excluded <= {r.row.row_number for r in reviewed}:
            raise CsvReviewMismatchError()

        kept = [r for r in reviewed if r.row.row_number not in excluded]
        to_add = [
            (r.match.game_id, r.row.title)
            for r in kept
            if r.status is CsvRowStatus.matched and isinstance(r.match, TitleMatch)
        ]
        added_count = await repositories.add_owned_games(user_id, platform, to_add)

        report = _match_report(kept)
        import_id = await _record_report(user_id, platform, report)
        needs_review_count = len(report.unmatched)
        skipped_count = len(reviewed) - added_count - needs_review_count
        log.info(
            "csv commit: user=%s platform=%s added=%d needs_review=%d skipped=%d",
            user_id, platform, added_count, needs_review_count, skipped_count,
        )
        return CsvCommitResponse(
            added=added_count,
            needs_review=needs_review_count,
            skipped=skipped_count,
            import_id=import_id,
        )


async def _review(user_id: UUID, platform: str, csv_text: str) -> list[_ReviewedRow]:
    """Parse, match and classify every row. Shared by preview and commit."""
    rows = parse_library_csv(csv_text)
    catalogue = catalogue_from_rows(await repositories.list_catalogue_games())
    titles_by_id = {game.game_id: game.title for game in catalogue}
    owned_ids = await repositories.list_owned_game_ids(user_id, platform)
    matcher = TitleMatcher(catalogue)

    seen_game_ids: set[UUID] = set()
    seen_titles: set[str] = set()
    reviewed: list[_ReviewedRow] = []
    for row in rows:
        if row.problem:
            reviewed.append(_ReviewedRow(row, CsvRowStatus.invalid, message=row.problem))
            continue
        result = matcher.match(ImportedTitle(title=row.title, steam_appid=row.steam_appid))
        if isinstance(result, TitleMatch):
            reviewed.append(_classify_match(row, result, titles_by_id, owned_ids, seen_game_ids))
            seen_game_ids.add(result.game_id)
        else:
            reviewed.append(_classify_unmatched(row, result, titles_by_id, seen_titles))
            seen_titles.add(result.normalised_title)
    return reviewed


def _classify_match(
    row: CsvRow,
    match: TitleMatch,
    titles_by_id: dict[UUID, str],
    owned_ids: set[UUID],
    seen_game_ids: set[UUID],
) -> _ReviewedRow:
    game_title = titles_by_id.get(match.game_id)
    if match.game_id in seen_game_ids:
        return _ReviewedRow(row, CsvRowStatus.duplicate, match, game_title,
                            "Same game as an earlier row.")
    if match.game_id in owned_ids:
        return _ReviewedRow(row, CsvRowStatus.already_owned, match, game_title,
                            "Already in your library.")
    return _ReviewedRow(row, CsvRowStatus.matched, match, game_title)


def _classify_unmatched(
    row: CsvRow,
    unmatched: UnmatchedTitle,
    titles_by_id: dict[UUID, str],
    seen_titles: set[str],
) -> _ReviewedRow:
    if unmatched.normalised_title in seen_titles:
        return _ReviewedRow(row, CsvRowStatus.duplicate, unmatched,
                            message="Same title as an earlier row.")
    if unmatched.reason == "ambiguous":
        names = [titles_by_id.get(g, "?") for g in unmatched.candidate_game_ids]
        shown = ", ".join(names[:_MAX_CANDIDATES_SHOWN])
        return _ReviewedRow(row, CsvRowStatus.ambiguous, unmatched,
                            message=f"Matches several games ({shown}). Saved for review.")
    return _ReviewedRow(row, CsvRowStatus.unmatched, unmatched,
                        message="No game found with this title. Saved for review.")


def _match_report(kept: list[_ReviewedRow]) -> MatchReport:
    """The library_imports report for the rows the user kept.

    Already-owned rows still count as matched: the match was right, the game
    just didn't need adding. Duplicates and invalid rows are left out.
    """
    report = MatchReport()
    for r in kept:
        if r.status in (CsvRowStatus.matched, CsvRowStatus.already_owned):
            report.matched.append(r.match)
        elif r.status in _NEEDS_REVIEW:
            report.unmatched.append(r.match)
    return report


async def _record_report(user_id: UUID, platform: str, report: MatchReport) -> UUID | None:
    """Store the report. The games are already added, so a failure here is
    logged and reported as a missing import_id instead of failing the upload."""
    try:
        return await repositories.record_library_import(user_id, platform, CSV_SOURCE, report)
    except Exception:
        log.exception("csv import report not recorded: user=%s", user_id)
        return None


def _to_result(reviewed: _ReviewedRow) -> CsvRowResult:
    game_id = reviewed.match.game_id if isinstance(reviewed.match, TitleMatch) else None
    return CsvRowResult(
        row_number=reviewed.row.row_number,
        title=reviewed.row.title,
        status=reviewed.status,
        game_id=game_id,
        game_title=reviewed.game_title,
        message=reviewed.message,
    )
