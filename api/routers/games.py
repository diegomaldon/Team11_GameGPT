"""GET /api/games/{game_id}: one game for the detail panel (TM11-78, REQ009).

HTTP only, shaped as the contract in docs/API.md. The repository reads the
games row on either database shape, and DeduplicationService (TM11-58) says
which platforms the user owns it on. The panel opens from a recommendation
card, the library and past searches; each of those only knows the game's id,
title and art, so this fills in the rest.

  404  game_not_found      no catalogue game has this id
  422  the id isn't a uuid
  503  game_detail_failed  anything else, logged with the cause

Registered after library_manual's GET /api/games/search (api/main.py), so
"search" is never read as a game id. Page-view logging is TM11-79.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from api.config import get_settings
from api.db import repositories
from api.models import GameCandidate, GameDetail
from api.services.deduplication import DeduplicationService

router = APIRouter(tags=["games"])
log = logging.getLogger("gamegpt.games")

GAME_NOT_FOUND_MESSAGE = "We couldn't find that game in the catalogue."
GAME_DETAIL_FAILED_MESSAGE = "Could not load this game's details right now."


@router.get(
    "/games/{game_id}",
    response_model=GameDetail,
    responses={404: {"description": "No catalogue game with this id."},
               503: {"description": "The catalogue couldn't be read."}},
)
async def get_game(game_id: UUID) -> GameDetail:
    """Description, genres, tags, platforms, scores and ownership for one catalogue game."""
    user_id = UUID(get_settings().dev_user_id)
    try:
        detail = await repositories.get_game_detail(game_id)
        if detail is not None:
            owned = await DeduplicationService().owned_platforms(
                user_id, [GameCandidate(game_id=detail.game_id, title=detail.title)]
            )
            detail.owned_on = list(owned.get(detail.game_id, ()))
    except Exception as exc:
        log.exception("game detail read failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "game_detail_failed", "message": GAME_DETAIL_FAILED_MESSAGE},
        ) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "game_not_found", "message": GAME_NOT_FOUND_MESSAGE},
        )
    return detail
