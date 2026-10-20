"""Which database shape DATABASE_URL points at.

Two shapes exist side by side:

  hosted  the Supabase schema (20260915120200_create_core_tables.sql onwards):
          games.game_id, owned_games.game_id, vectors in public.game_embeddings
  legacy  the local walking-skeleton slice (0001_init.sql): games.id,
          games.embedding, owned_games keyed by steam_appid and title

Services that read the catalogue ask once per process and pick their SQL. The
test is the one the hosted migrations use themselves: does games have game_id.
"""

from __future__ import annotations

from typing import Literal

from api.config import get_settings
from api.db.pool import connection

Shape = Literal["hosted", "legacy"]

_cache: dict[str, Shape] = {}


async def catalogue_shape() -> Shape:
    """The shape of the database in DATABASE_URL, cached per URL."""
    url = get_settings().database_url or ""
    if url not in _cache:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "select exists (select 1 from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'games' "
                    "and column_name = 'game_id')"
                )
                (is_hosted,) = await cur.fetchone()
        _cache[url] = "hosted" if is_hosted else "legacy"
    return _cache[url]


def reset_shape_cache() -> None:
    """Forget the cached shape (tests, or after migrating a database)."""
    _cache.clear()
