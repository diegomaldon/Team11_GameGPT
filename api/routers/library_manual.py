"""GET /api/games/search and POST /api/library/manual (TM11-54, REQ004).

HTTP only: ManualImportService does the work. Every expected failure becomes a
structured error, so the UI can branch on `error` and show `message` as is:

  404  game_not_found  the game_id isn't in the catalogue
  409  already_owned   the game is already in the library on that platform
  503  anything else, logged with the cause; the message stays generic

The user is the dev user, like every other route today. Real per-user auth is
an API-wide gap tracked on its own ticket (TM11-131).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from api.config import get_settings
from api.models import (
    GameSearchResponse,
    ManualAddRequest,
    ManualAddResponse,
)
from api.models.schemas import (
    GAME_SEARCH_DEFAULT_LIMIT,
    GAME_SEARCH_MAX_LENGTH,
    GAME_SEARCH_MAX_LIMIT,
)
from api.services.manual_import import (
    AlreadyOwnedError,
    GameNotFoundError,
    ManualImportService,
)

router = APIRouter(tags=["library"])
log = logging.getLogger("gamegpt.library_manual")

SEARCH_FAILED_MESSAGE = "Could not search for games right now."
ADD_FAILED_MESSAGE = "Could not add that game right now. Nothing was changed."

_STATUS = {
    GameNotFoundError: status.HTTP_404_NOT_FOUND,
    AlreadyOwnedError: status.HTTP_409_CONFLICT,
}


@router.get("/games/search", response_model=GameSearchResponse)
async def search_games(
    q: str = Query(..., max_length=GAME_SEARCH_MAX_LENGTH, description="Part of a game title."),
    limit: int = Query(GAME_SEARCH_DEFAULT_LIMIT, ge=1, le=GAME_SEARCH_MAX_LIMIT),
) -> GameSearchResponse:
    """Catalogue games for the add-a-game autocomplete. Fewer than 2 characters returns none."""
    try:
        items = await ManualImportService().search(q, limit)
    except Exception as exc:
        log.exception("game search failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "search_failed", "message": SEARCH_FAILED_MESSAGE},
        ) from exc
    return GameSearchResponse(items=items)


@router.post(
    "/library/manual",
    response_model=ManualAddResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_manual_game(req: ManualAddRequest) -> ManualAddResponse:
    """Add one catalogue game to the library, stored with import_method MANUAL."""
    try:
        return await ManualImportService().add(_user_id(), req.platform, req.game_id)
    except (GameNotFoundError, AlreadyOwnedError) as exc:
        raise HTTPException(
            status_code=_STATUS[type(exc)],
            detail={"error": exc.code, "message": exc.user_message},
        ) from exc
    except Exception as exc:
        log.exception("manual add failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "manual_import_failed", "message": ADD_FAILED_MESSAGE},
        ) from exc


def _user_id() -> UUID:
    return UUID(get_settings().dev_user_id)
