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
from typing import Any, Callable, Mapping, Sequence
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

_UPSERT_OWNED_GAMES_SQL = (
    "insert into owned_games "
    "(user_id, platform, platform_account_id, steam_appid, title, "
    " playtime_minutes, imported_at) "
    "values (%s, %s, %s, %s, %s, %s, now()) "
    # AC-02. The conflict target is the unique constraint declared in
    # 0001_init.sql. It is what makes a re-sync update in place instead of
    # inserting a second copy of the library, so the row count is stable across
    # any number of runs.
    "on conflict (user_id, platform, steam_appid) do update set "
    # A sync that cannot name a title should not erase one we already have.
    "title = coalesce(excluded.title, owned_games.title), "
    # AC-03. coalesce, not a plain assignment: the keyless offline fallback has
    # no account to attribute to, and it must not detach rows that a real sync
    # already attributed correctly.
    "platform_account_id = coalesce("
    "    excluded.platform_account_id, owned_games.platform_account_id), "
    # AC-02. Steam's playtime_forever is cumulative and never decreases, so a
    # re-sync should move playtime forward and never backward. greatest() also
    # means the 0-minute fallback rows cannot zero out real hours. The cost of
    # this choice is that a genuine downward correction would not take; that
    # trade is deliberate and written up in docs/library-sync-idempotency.md.
    "playtime_minutes = greatest("
    "    excluded.playtime_minutes, owned_games.playtime_minutes), "
    # AC-01. Unconditional: "when did a sync last see this row" is only true if
    # it moves on every run, including the runs that change nothing else.
    "imported_at = now()"
)


def _playtime_minutes(row: Mapping[str, Any]) -> int:
    """Coerce a row's playtime to a non-negative int.

    Accepts either our own `playtime_minutes` or Steam's raw `playtime_forever`
    so callers can hand over a GetOwnedGames payload unchanged. Anything
    missing, null or unparseable becomes 0 — the column is NOT NULL, and a
    title that reports no playtime is owned-but-never-played, not unknown.
    """
    raw = row.get("playtime_minutes")
    if raw is None:
        raw = row.get("playtime_forever")
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 0

@retry(**_RETRY)
async def ensure_platform_account(
    user_id: UUID, platform: str, external_id: str
) -> UUID:
    """Upsert the platform_accounts row for one link and return its id.

    AC-03 needs an account id before a single owned_games row is written, and
    the sync is the first thing that knows the steamID64, so the row is created
    here rather than assumed to exist.

    `do update set external_id = excluded.external_id` is a deliberate no-op
    write. `do nothing` would skip the row on conflict and RETURNING would hand
    back zero rows, which is exactly the common case — a user re-syncing an
    account they already linked.
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into platform_accounts (user_id, platform, external_id) "
                "values (%s, %s, %s) "
                "on conflict (user_id, platform, external_id) do update set "
                "external_id = excluded.external_id "
                "returning id",
                (str(user_id), platform, str(external_id)),
            )
            row = await cur.fetchone()
        await conn.commit()
    account_id = _as_uuid(row[0]) if row else None
    if account_id is None:  # pragma: no cover - RETURNING always yields a row
        raise RuntimeError("ensure_platform_account did not return an id")
    return account_id


@retry(**_RETRY)
async def attach_orphan_owned_games(
    user_id: UUID, platform_account_id: UUID, platform: str = "steam"
) -> int:
    """Attribute this user's unattributed rows on `platform` to an account.

    AC-03 for rows that predate attribution — the five seeded titles in
    supabase/seed.sql, and anything written before this ticket. Only touches
    rows where platform_account_id is null, so it can never move a row from one
    account to another.

    Returns how many rows were attached.
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update owned_games set platform_account_id = %s "
                "where user_id = %s and platform = %s "
                "and platform_account_id is null",
                (str(platform_account_id), str(user_id), platform),
            )
            attached = cur.rowcount or 0
        await conn.commit()
    return int(attached)


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
                "select game_id, title, steam_appid, platform, "
                "playtime_minutes, imported_at "
                "from owned_games where user_id = %s "
                # Most-played first: the library view should lead with what the
                # user actually plays, not with whatever sorts alphabetically.
                "order by playtime_minutes desc, title nulls last",
                (str(user_id),),
            )
            rows = await cur.fetchall()
    return [
        LibraryItem(
            game_id=_as_uuid(r[0]),
            title=r[1] or "",
            steam_appid=r[2],
            platform=r[3] or "steam",
            playtime_minutes=r[4] or 0,
            imported_at=r[5],
        )
        for r in rows
    ]


@retry(**_RETRY)
async def upsert_owned_games(
    user_id: UUID,
    rows: Sequence[Mapping[str, Any]],
    platform: str = "steam",
    platform_account_id: UUID | None = None,
) -> int:
    """Upsert owned_games rows for the user. Idempotent on (user, platform, appid).

    Re-running a sync updates the existing rows in place — playtime moves
    forward, imported_at moves to now, and the row count does not change. See
    `_UPSERT_OWNED_GAMES_SQL` above for the per-column rules.

    `platform_account_id` is the account the library was imported from. It is
    optional only because the keyless offline fallback has no real account to
    name; every live sync path supplies one.
    """
    if not rows:
        return 0
    account = str(platform_account_id) if platform_account_id is not None else None
    params = [
        (
            str(user_id),
            platform,
            account,
            row.get("steam_appid"),
            row.get("title"),
            _playtime_minutes(row),
        )
        for row in rows
    ]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(_UPSERT_OWNED_GAMES_SQL, params)
        await conn.commit()
    return len(params)
