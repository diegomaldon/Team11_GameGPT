"""XboxImportService: writes a user's Xbox title history to owned_games (TM11-56, REQ014).

The web app does the Xbox side. POST /api/xbox/import signs the user in again,
reads their title history from titlehub, and posts the titles here. This
service then:

  1. matches every title to the games catalogue with the TM11-48 TitleMatcher
  2. plans the write against the user's existing Xbox rows (plan_xbox_import)
  3. writes it in one transaction (repositories.apply_xbox_import)
  4. records the run and its unmatched titles, like a Steam sync does

Idempotent: each row is keyed on the Xbox titleId (owned_games.external_id),
so importing the same history twice updates rows and adds none. A title whose
game the user already added on Xbox by CSV or by hand is left alone and
counted as already_owned, so the library never shows that game twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import UUID

from api.db import repositories
from api.models import XboxImportResponse, XboxTitle
from api.services.title_matching import (
    ImportedTitle,
    MatchReport,
    TitleMatch,
    TitleMatcher,
    catalogue_from_rows,
)

log = logging.getLogger("gamegpt.xbox_import")

PLATFORM = "xbox"


@dataclass
class XboxImportPlan:
    """The writes one import needs. Built offline, so it is unit-tested without a DB."""

    inserts: list[tuple[str, str, UUID | None]] = field(default_factory=list)
    updates: list[tuple[UUID, str, UUID | None]] = field(default_factory=list)
    already_owned: list[str] = field(default_factory=list)  # titleIds left alone


def plan_xbox_import(
    existing: Sequence[Mapping[str, Any]],
    titles: Sequence[tuple[XboxTitle, UUID | None]],
) -> XboxImportPlan:
    """Decide, per title, whether to insert, update or skip.

    `existing` is the user's owned_games rows on Xbox (id, game_id, external_id).
    `titles` pairs each distinct title with its matched game_id, or None.

    - A titleId seen before updates that row.
    - A matched game already held by another Xbox row is skipped. A second row
      would break owned_games_user_platform_manual_game_key for CSV/manual rows,
      and would list the game twice for an earlier import's row.
    - Anything else is inserted.
    """
    plan = XboxImportPlan()
    by_external = {r["external_id"]: r for r in existing if r.get("external_id")}
    # game_id -> who holds it: an owned_games.id, or a titleId inserted in this plan
    holders: dict[UUID, object] = {r["game_id"]: r["id"] for r in existing if r.get("game_id")}

    for title, game_id in titles:
        row = by_external.get(title.title_id)
        if row is not None:
            holder = holders.get(game_id) if game_id else None
            if holder is not None and holder != row["id"]:
                # The game moved to another row (e.g. a CSV add). Keep this row's old link.
                game_id = row.get("game_id")
            plan.updates.append((row["id"], title.name, game_id))
            if game_id:
                holders[game_id] = row["id"]
            continue

        if game_id and game_id in holders:
            plan.already_owned.append(title.title_id)
            continue

        plan.inserts.append((title.title_id, title.name, game_id))
        if game_id:
            holders[game_id] = title.title_id
    return plan


def distinct_titles(titles: Sequence[XboxTitle]) -> list[XboxTitle]:
    """One entry per titleId, first wins. titlehub can list a title once per device."""
    seen: set[str] = set()
    out: list[XboxTitle] = []
    for t in titles:
        if t.title_id not in seen:
            seen.add(t.title_id)
            out.append(t)
    return out


class XboxImportService:
    async def import_titles(
        self, user_id: UUID, titles: Sequence[XboxTitle]
    ) -> XboxImportResponse:
        """Match, plan and write one Xbox import. Raises if the write fails;
        nothing is committed in that case."""
        titles = distinct_titles(titles)
        catalogue = catalogue_from_rows(await repositories.list_catalogue_games())
        matcher = TitleMatcher(catalogue)

        report = MatchReport()
        paired: list[tuple[XboxTitle, UUID | None]] = []
        for t in titles:
            result = matcher.match(ImportedTitle(title=t.name))
            if isinstance(result, TitleMatch):
                report.matched.append(result)
                paired.append((t, result.game_id))
            else:
                report.unmatched.append(result)
                paired.append((t, None))

        existing = await repositories.list_platform_owned_rows(user_id, PLATFORM)
        plan = plan_xbox_import(existing, paired)
        await repositories.apply_xbox_import(user_id, plan.inserts, plan.updates)

        import_id: UUID | None = None
        try:
            import_id = await repositories.record_library_import(
                user_id, PLATFORM, PLATFORM, report
            )
        except Exception:
            # Same rule as the Steam sync: the library is already committed, so a
            # missing report must not turn a good import into a failed one.
            log.exception("xbox import report not recorded: user=%s", user_id)

        log.info(
            "xbox import: user=%s total=%d added=%d updated=%d already_owned=%d "
            "match_rate=%.1f%%",
            user_id, len(titles), len(plan.inserts), len(plan.updates),
            len(plan.already_owned), report.match_rate * 100,
        )
        return XboxImportResponse(
            total=len(titles),
            added=len(plan.inserts),
            updated=len(plan.updates),
            already_owned=len(plan.already_owned),
            matched=len(report.matched),
            unmatched=len(report.unmatched),
            match_rate=report.match_rate,
            import_id=import_id,
        )
