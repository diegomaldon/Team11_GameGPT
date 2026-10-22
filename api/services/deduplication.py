"""DeduplicationService — ownership checks and dropping games the user owns.

SysML block: Deduplication. Reads owned_games for the user. TM11-58, serving
REQ007 (don't recommend owned games) and REQ008 (show where a game is owned).

On the hosted schema, owned_games.game_id points at the same games row the
vector store returns, so a candidate is owned when its game_id is, and the
platform comes from the linked platform_accounts row. On the legacy
0001_init.sql slice, owned_games.game_id can be null, so it also matches on
steam_appid, then normalized title, and the platform is a column on the row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from api.db import connection
from api.db.schema import catalogue_shape
from api.models import GameCandidate

_PUNCT = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS = re.compile(r"\s+")

# Same order as PLATFORM_ORDER in web/lib/library/unified.ts, so the badges the
# UI draws from this list come out in the order the library page uses.
PLATFORM_ORDER = ("steam", "xbox", "epic", "playstation")

_HOSTED_OWNED_SQL = (
    "select o.game_id, p.platform::text "
    "from public.owned_games o "
    "join public.platform_accounts p on p.platform_account_id = o.platform_account_id "
    "where o.user_id = %s and o.game_id = any(%s)"
)
_LEGACY_OWNED_SQL = (
    "select game_id, steam_appid, title, platform from owned_games where user_id = %s"
)


@dataclass(frozen=True)
class Ownership:
    """Whether the user owns one game, and on which platforms."""

    game_id: UUID
    platforms: tuple[str, ...] = ()

    @property
    def is_owned(self) -> bool:
        return bool(self.platforms)


def _sort_platforms(platforms: set[str]) -> tuple[str, ...]:
    """Known platforms in PLATFORM_ORDER, then anything else alphabetically."""
    def key(p: str) -> tuple[int, str]:
        rank = PLATFORM_ORDER.index(p) if p in PLATFORM_ORDER else len(PLATFORM_ORDER)
        return rank, p

    return tuple(sorted(platforms, key=key))


def normalize_title(title: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not title:
        return ""
    lowered = title.lower()
    stripped = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", stripped).strip()


class DeduplicationService:
    async def check_ownership(self, user_id: UUID, game: GameCandidate) -> Ownership:
        """Whether `user_id` owns `game` on any linked platform, and which ones."""
        platforms = await self.owned_platforms(user_id, [game])
        return Ownership(game_id=game.game_id, platforms=platforms.get(game.game_id, ()))

    async def owned_platforms(
        self, user_id: UUID, games: list[GameCandidate]
    ) -> dict[UUID, tuple[str, ...]]:
        """Map each owned game's game_id to the platforms it's owned on.

        Games the user doesn't own are left out. One query covers the whole
        list. Platforms are lowercase ("steam", "xbox", ...) in PLATFORM_ORDER,
        so the UI can draw a badge per entry.
        """
        if not games:
            return {}
        if await catalogue_shape() == "hosted":
            found = await self._hosted_platforms(user_id, games)
        else:
            found = await self._legacy_platforms(user_id, games)
        return {game_id: _sort_platforms(p) for game_id, p in found.items() if p}

    async def _hosted_platforms(
        self, user_id: UUID, games: list[GameCandidate]
    ) -> dict[UUID, set[str]]:
        game_ids = list({g.game_id for g in games})
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_HOSTED_OWNED_SQL, (user_id, game_ids))
                rows = await cur.fetchall()
        found: dict[UUID, set[str]] = {}
        for game_id, platform in rows:
            found.setdefault(game_id, set()).add(platform.lower())
        return found

    async def _legacy_platforms(
        self, user_id: UUID, games: list[GameCandidate]
    ) -> dict[UUID, set[str]]:
        by_game_id: dict[UUID, set[str]] = {}
        by_appid: dict[int, set[str]] = {}
        by_title: dict[str, set[str]] = {}
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_LEGACY_OWNED_SQL, (user_id,))
                for game_id, steam_appid, title, platform in await cur.fetchall():
                    platform = (platform or "steam").lower()
                    if game_id is not None:
                        by_game_id.setdefault(game_id, set()).add(platform)
                    if steam_appid is not None:
                        by_appid.setdefault(int(steam_appid), set()).add(platform)
                    normalized = normalize_title(title)
                    if normalized:
                        by_title.setdefault(normalized, set()).add(platform)

        # A copy can match on more than one key (a Steam row with both appid
        # and title), so the platforms from every key are unioned.
        found: dict[UUID, set[str]] = {}
        for g in games:
            platforms = set(by_game_id.get(g.game_id, ()))
            if g.steam_appid is not None:
                platforms |= by_appid.get(int(g.steam_appid), set())
            platforms |= by_title.get(normalize_title(g.title), set())
            if platforms:
                found.setdefault(g.game_id, set()).update(platforms)
        return found

    async def filter_owned(
        self, user_id: UUID, candidates: list[GameCandidate]
    ) -> list[GameCandidate]:
        """Return candidates the user does NOT already own.

        Preserves input order. Hosted: match on game_id. Legacy: steam_appid,
        then case/whitespace-normalized title.
        """
        if not candidates:
            return []

        if await catalogue_shape() == "hosted":
            async with connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "select game_id from public.owned_games where user_id = %s",
                        (user_id,),
                    )
                    owned_ids = {row[0] for row in await cur.fetchall()}
            return [c for c in candidates if c.game_id not in owned_ids]

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
