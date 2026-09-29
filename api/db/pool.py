"""Async Postgres connections, opened one place, with pgvector registered.

Both Agent B (vector search, dedup reads) and Agent C (persistence) use
`connection()`. Keeping the pgvector adapter registration here means callers
just pass/receive `list[float]` for embeddings.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg

from api.config import get_settings


def has_db() -> bool:
    return bool(get_settings().database_url)


@asynccontextmanager
async def connection() -> AsyncIterator[psycopg.AsyncConnection]:
    """Open a short-lived autocommit-off async connection.

    Usage:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(...)
            await conn.commit()

    Raises RuntimeError if DATABASE_URL is unset — callers that support an
    offline fallback must check `has_db()` first.
    """
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")

    conn = await psycopg.AsyncConnection.connect(settings.database_url)
    try:
        await _register_vector(conn)
        yield conn
    finally:
        await conn.close()


async def _register_vector(conn: psycopg.AsyncConnection) -> None:
    """Register the pgvector adapter so vector(1536) round-trips as list[float].

    No-op if the pgvector Python package or the DB extension is unavailable;
    callers can still bind embeddings as string literals if needed.
    """
    try:
        from pgvector.psycopg import register_vector_async

        await register_vector_async(conn)
    except Exception:
        pass
