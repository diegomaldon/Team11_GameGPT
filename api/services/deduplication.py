"""DeduplicationService — drops games the user already owns.

SysML block: Deduplication. Matches on steam_appid first, then normalized
title. Reads owned_games for the user.
"""

from __future__ import annotations

import re
from uuid import UUID

from api.db import connection
from api.models import GameCandidate

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_title(title: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not title:
        return ""
    lowered = title.lower()
    stripped = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", stripped).strip()


class DeduplicationService:
    async def filter_owned(
        self, user_id: UUID, candidates: list[GameCandidate]
    ) -> list[GameCandidate]:
        """Return candidates the user does NOT already own.

        Preserves input order. Match precedence: steam_appid, then
        case/whitespace-normalized title.
        """
        if not candidates:
            return []

        owned_appids: set[int] = set()
        owned_titles: set[str] = set()
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "select steam_appid, title from owned_games where user_id = %s",
                    (user_id,),
                )
                for steam_appid, title in await cur.fetchall():
                    if steam_appid is not None:
                        owned_appids.add(int(steam_appid))
                    normalized = normalize_title(title)
                    if normalized:
                        owned_titles.add(normalized)

        kept: list[GameCandidate] = []
        for c in candidates:
            if c.steam_appid is not None and int(c.steam_appid) in owned_appids:
                continue
            if normalize_title(c.title) in owned_titles:
                continue
            kept.append(c)
        return kept
