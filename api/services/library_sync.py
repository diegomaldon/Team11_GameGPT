"""LibrarySyncService — pulls a user's owned games from Steam.

SysML block: Library Sync. Real IPlayerService/GetOwnedGames call (needs only
an API key + public steamID64, no OAuth). With no STEAM_API_KEY, the
implementation falls back to seeded owned_games rows so the slice still runs.

The external Steam call is isolated in `_fetch_steam_games`, and the httpx
client is injectable, so the network hop can be faked in tests without a key.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from api.config import Settings, get_settings
from api.db import repositories
from api.models import LibraryItem, LibrarySyncResponse

log = logging.getLogger("gamegpt.library_sync")

_STEAM_URL = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"

# Tiny built-in library used only when there is no Steam key AND no seed rows,
# so the dedup step and the slice still have something to chew on offline.
_FALLBACK_GAMES: list[dict[str, Any]] = [
    {"steam_appid": 620, "title": "Portal 2"},
    {"steam_appid": 292030, "title": "The Witcher 3: Wild Hunt"},
    {"steam_appid": 413150, "title": "Stardew Valley"},
    {"steam_appid": 1091500, "title": "Cyberpunk 2077"},
]


class LibrarySyncService:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Injected client lets tests fake the Steam hop; None => real network.
        self._http_client = http_client

    async def sync(self, user_id: UUID, steam_id: str) -> LibrarySyncResponse:
        """Fetch the Steam library for `steam_id` and upsert owned_games.

        Returns how many rows landed and whether the source was the live Steam
        API ('steam') or the seeded fallback ('seed').
        """
        if self._settings.steam_api_key:
            games = await self._fetch_steam_games(steam_id)
            rows = [
                {"steam_appid": g.get("appid"), "title": g.get("name")}
                for g in games
                if g.get("appid") is not None
            ]
            synced = await repositories.upsert_owned_games(user_id, rows, platform="steam")
            log.info("steam sync: user=%s steam_id=%s synced=%d", user_id, steam_id, synced)
            return LibrarySyncResponse(synced=synced, source="steam")

        # No key: prefer whatever the DB seed (supabase/seed.sql) already holds.
        existing = await repositories.count_owned_games(user_id)
        if existing > 0:
            log.info("seed sync: user=%s reusing %d seeded rows", user_id, existing)
            return LibrarySyncResponse(synced=existing, source="seed")

        # No key and no seed rows: plant the built-in fallback so dedup works.
        synced = await repositories.upsert_owned_games(
            user_id, _FALLBACK_GAMES, platform="steam"
        )
        log.info("seed sync: user=%s inserted %d fallback rows", user_id, synced)
        return LibrarySyncResponse(synced=synced, source="seed")

    async def list_owned(self, user_id: UUID) -> list[LibraryItem]:
        """Return the user's current owned-games library."""
        return await repositories.list_owned_games(user_id)

    # ── the one external call, kept behind the service so it can be faked ──
    async def _fetch_steam_games(self, steam_id: str) -> list[dict[str, Any]]:
        params = {
            "key": self._settings.steam_api_key,
            "steamid": steam_id,
            "include_appinfo": 1,
            "format": "json",
        }
        if self._http_client is not None:
            resp = await self._http_client.get(_STEAM_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        else:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(_STEAM_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
        return data.get("response", {}).get("games", []) or []
