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
from typing import TYPE_CHECKING, Any, Callable, Mapping, Sequence
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

if TYPE_CHECKING:  # runtime import would cycle through api.services.__init__
    from api.services.embedding_pipeline import GameEmbedding
    from api.services.title_matching import MatchReport

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
                "select game_id, title, steam_appid, platform, playtime_minutes "
                "from owned_games where user_id = %s "
                # Most-played first: the library view leads with what the user
                # actually plays, not whatever sorts alphabetically.
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
        )
        for r in rows
    ]


@retry(**_RETRY)
async def upsert_owned_games(
    user_id: UUID, rows: Sequence[Mapping[str, Any]], platform: str = "steam"
) -> int:
    """Upsert owned_games rows for the user. Idempotent on (user, platform, appid).

    Each row may carry a `game_id` from title matching; rows without one keep a
    NULL game_id (and stay in the unmatched review queue).
    """
    if not rows:
        return 0
    params = [
        (
            str(user_id),
            platform,
            row.get("steam_appid"),
            row.get("title"),
            # TM11-46: Steam reports playtime_forever in minutes. Absent on a
            # non-Steam import, so default rather than write NULL into a NOT NULL
            # column. See 20261006120000_owned_games_playtime.sql.
            int(row.get("playtime_minutes") or 0),
            str(row["game_id"]) if row.get("game_id") else None,
        )
        for row in rows
    ]
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into owned_games "
                "(user_id, platform, steam_appid, title, playtime_minutes, game_id) "
                "values (%s, %s, %s, %s, %s, %s) "
                "on conflict (user_id, platform, steam_appid) do update set "
                "title = excluded.title, game_id = excluded.game_id, "
                # A re-sync should move playtime forward, never backward: Steam
                # is the source of truth and playtime only grows. Taking the max
                # also means a partial/failed sync cannot zero out real hours.
                "playtime_minutes = greatest("
                "    owned_games.playtime_minutes, excluded.playtime_minutes)",
                params,
            )
        await conn.commit()
    return len(params)


# ─────────────────────── library import (TM11-49) ───────────────────────

# Rows per savepoint. Progress is reported after each chunk, so this is also the
# UI's update granularity: a 500-title library moves in 10 visible steps.
IMPORT_CHUNK = 50

# Same playtime rule as upsert_owned_games: a re-sync only moves it forward.
_OWNED_UPSERT = (
    "insert into owned_games "
    "(user_id, platform, steam_appid, title, playtime_minutes, game_id) "
    "values (%s, %s, %s, %s, %s, %s) "
    "on conflict (user_id, platform, steam_appid) do update set "
    "title = excluded.title, game_id = excluded.game_id, "
    "playtime_minutes = greatest("
    "    owned_games.playtime_minutes, excluded.playtime_minutes)"
)

# A bad title (out-of-range id, bad text, constraint) — isolate it and carry on.
# Connection-level errors (OperationalError / InterfaceError) are NOT in here:
# they abort the run, and the outer transaction rolls everything back.
_ROW_ERRORS = (psycopg.DataError, psycopg.IntegrityError, psycopg.ProgrammingError)

ImportProgress = Callable[[int, int, list[tuple[Mapping[str, Any], str]]], None]


def _row_error_reason(exc: Exception) -> str:
    diag = getattr(exc, "diag", None)
    msg = getattr(diag, "message_primary", None) or next(iter(str(exc).splitlines()), "")
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


async def import_owned_games(
    user_id: UUID,
    rows: Sequence[Mapping[str, Any]],
    platform: str = "steam",
    *,
    chunk_size: int = IMPORT_CHUNK,
    on_progress: ImportProgress | None = None,
    conn_factory: Callable[[], Any] | None = None,
) -> tuple[int, list[tuple[Mapping[str, Any], str]]]:
    """Import a whole library in ONE transaction, isolating per-title failures.

    - Each chunk runs in a savepoint. If it fails, the chunk is replayed row by
      row (each in its own savepoint) so only the offending titles are dropped.
    - Nothing commits until every chunk is done. Any other error (connection
      lost, server gone) propagates out of the outer block, which rolls back:
      a failed run leaves the user's previous library exactly as it was.

    Returns (synced, failures) where failures is [(row, reason)]. Not wrapped
    in @retry: a retry would replay progress callbacks the UI already showed.
    """
    factory = conn_factory or connection
    synced = 0
    failures: list[tuple[Mapping[str, Any], str]] = []

    def params(row: Mapping[str, Any]) -> tuple:
        return (
            str(user_id),
            platform,
            row.get("steam_appid"),
            row.get("title"),
            int(row.get("playtime_minutes") or 0),  # absent on the seed fallback
            # from title matching; NULL when the title is in the review queue
            str(row["game_id"]) if row.get("game_id") else None,
        )

    async with factory() as conn:
        async with conn.transaction():
            for start in range(0, len(rows), chunk_size):
                chunk = rows[start : start + chunk_size]
                try:
                    async with conn.transaction():
                        async with conn.cursor() as cur:
                            await cur.executemany(_OWNED_UPSERT, [params(r) for r in chunk])
                    synced += len(chunk)
                except _ROW_ERRORS:
                    for row in chunk:
                        try:
                            async with conn.transaction():
                                async with conn.cursor() as cur:
                                    await cur.execute(_OWNED_UPSERT, params(row))
                            synced += 1
                        except _ROW_ERRORS as exc:
                            reason = _row_error_reason(exc)
                            log.warning("owned_games import: skip appid=%s: %s",
                                        row.get("steam_appid"), reason)
                            failures.append((row, reason))
                if on_progress is not None:
                    on_progress(start + len(chunk), synced, failures)
    return synced, failures


# ─────────────────────────── title matching ───────────────────────────


@retry(**_RETRY)
async def list_catalogue_games() -> list[dict[str, Any]]:
    """Every games row's match keys: game_id, title, steam_appid."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("select game_id, title, steam_appid from public.games")
            rows = await cur.fetchall()
    return [{"game_id": r[0], "title": r[1], "steam_appid": r[2]} for r in rows]


@retry(**_RETRY)
async def record_library_import(
    user_id: UUID,
    platform: str,
    source: str,
    report: MatchReport,
) -> UUID:
    """Write one library_imports row (counts + match rate) and upsert the
    unmatched titles into the review queue. Returns the new import_id.

    One transaction: the run row and its unmatched titles land together.
    """
    counts = report.counts_by_method()
    platform_enum = platform.upper()
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into public.library_imports "
                "(user_id, platform, source, total_titles, matched_appid, matched_exact, "
                " matched_normalised, matched_edition, unmatched, match_rate) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning import_id",
                (
                    str(user_id), platform_enum, source, report.total,
                    counts["appid"], counts["exact"], counts["normalised"],
                    counts["edition"], len(report.unmatched), report.match_rate,
                ),
            )
            row = await cur.fetchone()
            import_id = _as_uuid(row[0]) if row else None
            if import_id is None:  # pragma: no cover - RETURNING always yields a row
                raise RuntimeError("record_library_import did not return an id")

            if report.unmatched:
                # Re-seen titles refresh their pointers; a reviewer's
                # resolved/ignored status is left alone.
                await cur.executemany(
                    "insert into public.unmatched_import_titles "
                    "(user_id, platform, source_title, external_id, normalised_title, "
                    " reason, candidate_game_ids, first_import_id, last_import_id) "
                    "values (%s, %s, %s, %s, %s, %s, %s::uuid[], %s, %s) "
                    "on conflict (user_id, platform, source_title) do update set "
                    "external_id = excluded.external_id, "
                    "normalised_title = excluded.normalised_title, "
                    "reason = excluded.reason, "
                    "candidate_game_ids = excluded.candidate_game_ids, "
                    "last_import_id = excluded.last_import_id, "
                    "last_seen_at = now()",
                    [
                        (
                            str(user_id), platform_enum, u.imported.title,
                            str(u.imported.steam_appid)
                            if u.imported.steam_appid is not None else None,
                            u.normalised_title, u.reason,
                            [str(g) for g in u.candidate_game_ids],
                            str(import_id), str(import_id),
                        )
                        for u in report.unmatched
                    ],
                )
        await conn.commit()
    return import_id


# ─────────────────────── CSV library import (TM11-55) ───────────────────────


@retry(**_RETRY)
async def list_owned_game_ids(user_id: UUID, platform: str) -> set[UUID]:
    """game_ids the user already owns on `platform`, for duplicate checks."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select game_id from owned_games "
                "where user_id = %s and platform = %s and game_id is not null",
                (str(user_id), platform),
            )
            rows = await cur.fetchall()
    return {game_id for game_id in (_as_uuid(r[0]) for r in rows) if game_id is not None}


@retry(**_RETRY)
async def add_owned_games(
    user_id: UUID, platform: str, games: Sequence[tuple[UUID, str]]
) -> int:
    """Add (game_id, title) pairs the user imported by hand. Returns how many were new.

    A game already in the library is skipped, never overwritten: `on conflict
    do nothing` relies on owned_games_user_platform_manual_game_key, so two
    uploads racing each other still can't add the same game twice. One
    statement, so the whole batch lands or none of it does. Safe to retry.
    """
    if not games:
        return 0
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into owned_games (user_id, platform, game_id, title) "
                "select %s, %s, g.game_id, g.title "
                "from unnest(%s::uuid[], %s::text[]) as g(game_id, title) "
                "on conflict do nothing "
                "returning game_id",
                (
                    str(user_id),
                    platform,
                    [str(game_id) for game_id, _ in games],
                    [title for _, title in games],
                ),
            )
            added = await cur.fetchall()
        await conn.commit()
    return len(added)


# ─────────────────── manual title entry (TM11-54) ───────────────────

# "!" rather than a backslash, so the escape survives Python and SQL quoting
# without doubling.
_LIKE_ESCAPE = "!"


def _like_pattern(text: str) -> str:
    """Escape LIKE wildcards so a user typing "100%" searches for it literally."""
    for ch in (_LIKE_ESCAPE, "%", "_"):
        text = text.replace(ch, _LIKE_ESCAPE + ch)
    return text


@retry(**_RETRY)
async def search_catalogue_games(query: str, limit: int) -> list[dict[str, Any]]:
    """Games whose title contains `query`, for the add-a-game autocomplete.

    Titles that start with the query come first, then shorter titles, so
    "hades" offers "Hades" before "Hades II" and both before "Shades of Doom".
    """
    pattern = _like_pattern(query)
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select game_id, title, steam_appid from public.games "
                "where title ilike %s escape '!' "
                "order by (title ilike %s escape '!') desc, length(title), title "
                "limit %s",
                (f"%{pattern}%", f"{pattern}%", limit),
            )
            rows = await cur.fetchall()
    return [{"game_id": r[0], "title": r[1], "steam_appid": r[2]} for r in rows]


@retry(**_RETRY)
async def get_catalogue_game(game_id: UUID) -> dict[str, Any] | None:
    """One games row's game_id, title and steam_appid, or None."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select game_id, title, steam_appid from public.games where game_id = %s",
                (str(game_id),),
            )
            row = await cur.fetchone()
    if row is None:
        return None
    return {"game_id": row[0], "title": row[1], "steam_appid": row[2]}


@retry(**_RETRY)
async def add_manual_game(user_id: UUID, platform: str, game_id: UUID, title: str) -> bool:
    """Add one hand-picked game with import_method MANUAL. False if already owned.

    `on conflict do nothing` relies on owned_games_user_platform_manual_game_key
    (TM11-55), so two adds racing each other still store one row. Safe to retry.
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "insert into owned_games (user_id, platform, game_id, title, import_method) "
                "values (%s, %s, %s, %s, 'MANUAL') "
                "on conflict do nothing "
                "returning game_id",
                (str(user_id), platform, str(game_id), title),
            )
            added = await cur.fetchone()
        await conn.commit()
    return added is not None


# ─────────────────── Xbox library import (TM11-56) ───────────────────


@retry(**_RETRY)
async def list_platform_owned_rows(user_id: UUID, platform: str) -> list[dict[str, Any]]:
    """The user's owned_games rows on `platform`: id, game_id and external_id."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select id, game_id, external_id from owned_games "
                "where user_id = %s and platform = %s",
                (str(user_id), platform),
            )
            rows = await cur.fetchall()
    return [
        {"id": _as_uuid(r[0]), "game_id": _as_uuid(r[1]), "external_id": r[2]} for r in rows
    ]


@retry(**_RETRY)
async def apply_xbox_import(
    user_id: UUID,
    inserts: Sequence[tuple[str, str, UUID | None]],
    updates: Sequence[tuple[UUID, str, UUID | None]],
) -> None:
    """Write one Xbox import in one transaction: all of it lands or none of it does.

    inserts  (external_id, title, game_id) for titles not seen before
    updates  (owned_games.id, title, game_id) for rows from an earlier import

    The insert upserts on owned_games_user_platform_external_id_key, so two
    imports racing each other still store one row per title. Safe to retry.
    """
    uid = str(user_id)
    async with connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                if inserts:
                    await cur.executemany(
                        "insert into owned_games "
                        "(user_id, platform, external_id, title, game_id) "
                        "values (%s, 'xbox', %s, %s, %s) "
                        "on conflict (user_id, platform, external_id) "
                        "where external_id is not null do update set "
                        "title = excluded.title, game_id = excluded.game_id",
                        [
                            (uid, external_id, title, str(game_id) if game_id else None)
                            for external_id, title, game_id in inserts
                        ],
                    )
                if updates:
                    await cur.executemany(
                        "update owned_games set title = %s, game_id = %s "
                        "where id = %s and user_id = %s",
                        [
                            (title, str(game_id) if game_id else None, str(row_id), uid)
                            for row_id, title, game_id in updates
                        ],
                    )


# ─────────────────── game embeddings (TM11-39) ───────────────────


@retry(**_RETRY)
async def list_games_with_document_hash(model: str) -> list[dict[str, Any]]:
    """Every catalogue game, with the hash and template of its last `model` vector.

    `document_hash` and `template_version` are None for a game with no vector
    from `model` yet. The pipeline compares them to a fresh hash and the
    current template to skip unchanged games (TM11-41, TM11-38).
    Ordered by game_id, so reruns walk the catalogue in the same order.
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select g.game_id, g.title, g.description, g.genres, g.tags, "
                "e.document_hash, e.template_version "
                "from public.games g "
                "left join public.game_embeddings e "
                "  on e.game_id = g.game_id and e.model = %s "
                "order by g.game_id",
                (model,),
            )
            rows = await cur.fetchall()
    return [
        {"game_id": r[0], "title": r[1], "description": r[2], "genres": r[3], "tags": r[4],
         "document_hash": r[5], "template_version": r[6]}
        for r in rows
    ]


@retry(**_RETRY)
async def upsert_game_embeddings(rows: Sequence[GameEmbedding]) -> None:
    """Store a batch of vectors in one transaction. Re-embedding replaces the row.

    The primary key (game_id, model) keeps one row per game per model.
    """
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into public.game_embeddings "
                "(game_id, model, dimensions, embedding, document_hash, token_count, "
                "template_version) "
                "values (%s, %s, %s, %s, %s, %s, %s) "
                "on conflict (game_id, model) do update set "
                "dimensions = excluded.dimensions, "
                "embedding = excluded.embedding, "
                "document_hash = excluded.document_hash, "
                "token_count = excluded.token_count, "
                "template_version = excluded.template_version, "
                "embedded_at = now()",
                [
                    (
                        str(row.game_id), row.model, row.dimensions, row.embedding,
                        row.document_hash, row.token_count, row.template_version,
                    )
                    for row in rows
                ],
            )
        await conn.commit()


@retry(**_RETRY)
async def count_game_embeddings(model: str) -> tuple[int, int]:
    """(games in the catalogue, games with a vector from `model`)."""
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select (select count(*) from public.games), "
                "(select count(*) from public.game_embeddings where model = %s)",
                (model,),
            )
            catalogue_count, embedded_count = await cur.fetchone()
    return catalogue_count, embedded_count
