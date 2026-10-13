"""ManualImportService: add one game to the library by hand.

TM11-54, REQ004: the fallback for any platform without a library API (Epic,
and Xbox until its own link ships).

  search  catalogue titles for the add-a-game autocomplete. Writes nothing.
  add     add one catalogue game, chosen from those suggestions, on one
          platform. Stored with import_method MANUAL.

Only catalogue games can be added. A free-typed title would be a library row
with no game_id, which ownership filtering (REQ007) can't use.

Duplicates are refused by owned_games_user_platform_manual_game_key, the index
the CSV upload added (TM11-55), so two clicks racing each other still store
one row. The CSV upload's own write path is left alone.

Logs carry ids only. A library is personal data, so titles stay out.
"""

from __future__ import annotations

import logging
from uuid import UUID

from api.db import repositories
from api.models import GameSearchResult, ManualAddResponse
from api.models.schemas import GAME_SEARCH_MIN_LENGTH, ManualPlatform

log = logging.getLogger("gamegpt.manual_import")


class ManualImportError(Exception):
    """An expected refusal. `code` is stable; `user_message` is safe to show."""

    code = "manual_import_failed"
    user_message = "Could not add that game right now."


class GameNotFoundError(ManualImportError):
    code = "game_not_found"
    user_message = "That game isn't in the catalogue. Pick one from the suggestions."


class AlreadyOwnedError(ManualImportError):
    code = "already_owned"
    user_message = "That game is already in your library on this platform."


class ManualImportService:
    async def search(self, query: str, limit: int) -> list[GameSearchResult]:
        """Up to `limit` catalogue games whose title contains `query`."""
        text = " ".join(query.split())  # "  hollow   knight " -> "hollow knight"
        if len(text) < GAME_SEARCH_MIN_LENGTH:
            return []
        rows = await repositories.search_catalogue_games(text, limit)
        return [GameSearchResult(**row) for row in rows]

    async def add(self, user_id: UUID, platform: ManualPlatform, game_id: UUID) -> ManualAddResponse:
        """Add the game, or raise GameNotFoundError / AlreadyOwnedError."""
        game = await repositories.get_catalogue_game(game_id)
        if game is None:
            raise GameNotFoundError()
        if not await repositories.add_manual_game(user_id, platform, game_id, game["title"]):
            raise AlreadyOwnedError()

        log.info("manual add: user=%s platform=%s game=%s", user_id, platform, game_id)
        return ManualAddResponse(game_id=game_id, title=game["title"], platform=platform)
