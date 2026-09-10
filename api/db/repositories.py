"""Async persistence helpers for the GameGPT slice.

Agent C owns this module. Every write goes through `api.db.connection()` (the
shared psycopg async connection from `pool.py`) and is retried up to two times
on a transient DB failure — the team's rainy-day scenario for a flaky Postgres.
Retries only fire on connection-level errors (OperationalError / InterfaceError);
a missing DATABASE_URL or a programming error propagates immediately so the
router can turn it into a structured response instead of looping pointlessly.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence
from uuid import UUID

import psycopg
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from api.db import connection
from api.models import FeedbackRequest, LibraryItem, Recommendation

log = logging.getLogger("gamegpt.db")

# stop_after_attempt(3) == the initial try + up to 2 retries.
_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.1, max=1.0),
    retry=retry_if_exception_type((psycopg.OperationalError, psycopg.InterfaceError)),
    reraise=True,
)


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


# ─────────────────────────── recommend flow ───────────────────────────


@retry(**_RETRY)
async def insert_query(user_id: UUID, text: str) -> UUID:
    """Persist one POST /api/recommend and return the new queries.id."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into queries (user_id, text) values (%s, %s) returning id",
                (str(user_id), text),
            )
            row = await cur.fetchone()
        await conn.commit()
    query_id = _as_uuid(row[0]) if row else None
    if query_id is None:  # pragma: no cover - RETURNING always yields a row
        raise RuntimeError("insert_query did not return an id")
    return query_id


@retry(**_RETRY)
async def insert_recommendations(
    query_id: UUID, recommendations: Sequence[Recommendation]
) -> int:
    """Persist the ranked recommendations for a query. Idempotent per rank."""
    if not recommendations:
        return 0
    params = [
        (
            str(query_id),
            str(r.game_id) if r.game_id else None,
            r.rank,
            r.title,
            r.reason,
        )
        for r in recommendations
    ]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into recommendations (query_id, game_id, rank, title, reason) "
                "values (%s, %s, %s, %s, %s) "
                "on conflict (query_id, rank) do update set "
                "game_id = excluded.game_id, title = excluded.title, reason = excluded.reason",
                params,
            )
        await conn.commit()
    return len(params)


# ─────────────────────────── feedback flow ───────────────────────────


@retry(**_RETRY)
async def insert_feedback(req: FeedbackRequest) -> None:
    """Persist one thumbs up/down. Does not affect ranking in the skeleton."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into recommendation_feedback "
                "(query_id, game_id, title, rank, vote) values (%s, %s, %s, %s, %s)",
                (
                    str(req.query_id),
                    str(req.game_id) if req.game_id else None,
                    req.title,
                    req.rank,
                    req.vote.value,
                ),
            )
        await conn.commit()


# ─────────────────────────── library flow ───────────────────────────


@retry(**_RETRY)
async def count_owned_games(user_id: UUID) -> int:
    """How many owned_games rows the user already has (seed detection)."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*) from owned_games where user_id = %s",
                (str(user_id),),
            )
            row = await cur.fetchone()
    return int(row[0]) if row else 0


@retry(**_RETRY)
async def list_owned_games(user_id: UUID) -> list[LibraryItem]:
    """Read the user's cross-platform library as LibraryItems."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select game_id, title, steam_appid, platform "
                "from owned_games where user_id = %s order by title nulls last",
                (str(user_id),),
            )
            rows = await cur.fetchall()
    return [
        LibraryItem(
            game_id=_as_uuid(r[0]),
            title=r[1] or "",
            steam_appid=r[2],
            platform=r[3] or "steam",
        )
        for r in rows
    ]


@retry(**_RETRY)
async def upsert_owned_games(
    user_id: UUID, rows: Sequence[Mapping[str, Any]], platform: str = "steam"
) -> int:
    """Upsert owned_games rows for the user. Idempotent on (user, platform, appid)."""
    if not rows:
        return 0
    params = [
        (str(user_id), platform, row.get("steam_appid"), row.get("title"))
        for row in rows
    ]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into owned_games (user_id, platform, steam_appid, title) "
                "values (%s, %s, %s, %s) "
                "on conflict (user_id, platform, steam_appid) do update set "
                "title = excluded.title",
                params,
            )
        await conn.commit()
    return len(params)
