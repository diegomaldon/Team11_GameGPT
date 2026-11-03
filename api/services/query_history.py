"""Saves each recommend call to the user's history in the background (TM11-64, REQ037).

The recommend route hands record_query to FastAPI as a background task, so the
user has their results before the write starts. A failed save can't reach
them any more, so it is logged with the query id (and, through the request
context, the request id) instead of raised.

Not a SysML block: the persistence step the RAG Pipeline leaves to the router.
"""

from __future__ import annotations

import logging
from typing import Sequence
from uuid import UUID

from api.db import repositories
from api.models import Recommendation

log = logging.getLogger("gamegpt.history")


async def record_query(
    *, query_id: UUID, user_id: UUID, query: str, recommendations: Sequence[Recommendation],
) -> None:
    """Save one query and its results. Never raises."""
    try:
        await repositories.save_query_history(
            query_id=query_id, user_id=user_id, query=query, recommendations=recommendations,
        )
    except Exception:
        log.exception("query history save failed", extra={"query_id": str(query_id)})
