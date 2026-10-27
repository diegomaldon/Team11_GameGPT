"""VectorStore — semantic top-k over the games knowledge base.

SysML block: Vector Store. pgvector cosine similarity; k defaults to 20.
The interface is deliberately narrow so pgvector can later be swapped for a
managed vector DB without touching callers.

Reads whichever shape DATABASE_URL has (api/db/schema.py):

  hosted  public.game_embeddings joined to public.games, filtered to this
          service's model and cast to its size, so the partial HNSW index from
          20261018120000_game_embeddings_hnsw_index.sql serves it (TM11-40)
  legacy  games.embedding on the local 0001_init.sql slice

Platform and genre filters (TM11-43) go in the query's WHERE clause, so the
database applies them before it takes the top k. Filtering the k results
afterwards would quietly return fewer games than asked for.
"""

from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

from api.config import get_settings
from api.db import connection
from api.db.schema import catalogue_shape
from api.models import GameCandidate
from api.services.embedding import EMBEDDING_DIM


def _to_vector_literal(embedding: list[float]) -> str:
    """Render an embedding as a pgvector text literal: '[0.1,0.2,...]'.

    Cast to ::vector in SQL so the query works whether or not the pgvector
    psycopg adapter registered.
    """
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


@dataclass(frozen=True)
class SearchFilters:
    """Hard constraints on a search. Empty means no constraint.

    A game has to pass every filter that is set; within one, any value will
    do. platforms=("steam", "xbox") keeps games on either store. Platforms are
    "steam", "xbox" or "epic". Genres match ignoring case.
    """

    platforms: tuple[str, ...] = ()
    genres: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.platforms or self.genres)


NO_FILTERS = SearchFilters()


def _genre_match(column: sql.Composable) -> sql.Composed:
    return sql.SQL(
        "exists (select 1 from unnest({}) as genre where lower(genre) = any(%(genres)s))"
    ).format(column)


def legacy_top_k_sql(filters: SearchFilters = NO_FILTERS) -> sql.Composed:
    """The query for the local 0001_init.sql slice. Named parameters `vec` and `k`."""
    where = [sql.SQL("embedding is not null")]
    if filters.platforms:
        # No platform column here: every game in this slice came from Steam.
        on_steam = "steam" in filters.platforms
        where.append(sql.SQL("steam_appid is not null" if on_steam else "false"))
    if filters.genres:
        where.append(_genre_match(sql.SQL("genres")))
    return sql.SQL(
        "select id, title, description, genres, tags, developer, "
        "review_score, steam_appid, (embedding <=> %(vec)s::vector) as distance "
        "from games "
        "where {where} "
        "order by distance asc "
        "limit %(k)s"
    ).format(where=sql.SQL(" and ").join(where))


def hosted_top_k_sql(
    model: str, dimensions: int, filters: SearchFilters = NO_FILTERS,
) -> sql.Composed:
    """The hosted query, with the model and size written in as literals.

    The partial index only serves a query whose WHERE and ORDER BY match its
    definition. Literals let the planner prove that on every call, rather
    than depending on how it plans a bound parameter. The operator is
    schema-qualified so the query does not depend on `extensions` being on the
    search_path. Takes named parameters `vec` and `k`, since the vector
    appears twice.
    """
    vector_type = sql.SQL("extensions.vector({})").format(sql.Literal(dimensions))
    distance = sql.SQL("e.embedding::{vt} OPERATOR(extensions.<=>) %(vec)s::{vt}").format(vt=vector_type)
    where = [sql.SQL("e.model = {}").format(sql.Literal(model))]
    if filters.platforms:
        where.append(sql.SQL("g.available_platforms && %(platforms)s::public.platform_type[]"))
    if filters.genres:
        where.append(_genre_match(sql.SQL("g.genres")))
    return sql.SQL(
        "select g.game_id, g.title, g.description, g.genres, g.tags, g.developers, "
        "g.review_score, g.steam_appid, {distance} as distance "
        "from public.game_embeddings e "
        "join public.games g on g.game_id = e.game_id "
        "where {where} "
        "order by {distance} "
        "limit %(k)s"
    ).format(distance=distance, where=sql.SQL(" and ").join(where))


def _filter_params(filters: SearchFilters, hosted: bool) -> dict:
    params = {}
    if filters.platforms and hosted:
        params["platforms"] = [p.upper() for p in filters.platforms]  # platform_type is upper case
    if filters.genres:
        params["genres"] = [g.lower() for g in filters.genres]
    return params


# pgvector's default hnsw.ef_search: the candidate list an HNSW scan keeps.
# A list smaller than k lowers recall for the larger k /api/search allows
# (up to 50), and Diego saw a scan come back with only 40 rows on #37
# (pgvector 0.8.7). A list of at least k costs little at this size.
HNSW_DEFAULT_EF_SEARCH = 40

# Transaction-local, so it lasts only for this search. The connection is
# autocommit-off, so the select below runs in the same transaction.
_SET_EF_SEARCH_SQL = sql.SQL("select set_config('hnsw.ef_search', %s, true)")


def ef_search_for(k: int) -> int:
    """The HNSW search list size that lets a scan return all `k` rows."""
    return max(k, HNSW_DEFAULT_EF_SEARCH)


# HNSW applies a WHERE filter to the rows its scan found, so a filter that
# strikes out most of the search list leaves fewer than k. An iterative scan
# (pgvector 0.8+) keeps going until k rows pass, still in distance order.
_SET_ITERATIVE_SCAN_SQL = sql.SQL("select set_config('hnsw.iterative_scan', 'strict_order', true)")


# The legacy slice's IVFFlat index has lists = 100 (0001_init.sql, 0002) over a
# catalogue of ~170 games, so most lists hold one game or none. pgvector scans
# one list by default, so an index scan can return 0 rows. Which plan runs
# depends on whether the table has been analyzed, which made the seeded CI test
# flaky. Probing every list makes the search exact.
IVFFLAT_LISTS = 100
_SET_PROBES_SQL = sql.SQL("select set_config('ivfflat.probes', %s, true)")


def _similarity(distance: float) -> float:
    # Clamp: floating error / non-normalized vectors can nudge outside [0, 1].
    return max(0.0, min(1.0, 1.0 - float(distance)))


class VectorStore:
    def __init__(self, model: str | None = None, dimensions: int = EMBEDDING_DIM) -> None:
        self.model = model or get_settings().embedding_model
        self.dimensions = dimensions

    async def top_k(
        self, embedding: list[float], k: int = 20, filters: SearchFilters = NO_FILTERS,
    ) -> list[GameCandidate]:
        """Return up to `k` games most similar to `embedding`, cosine-ranked.

        Only games that pass `filters` count, so fewer than `k` (or none) come
        back when fewer games match. Each candidate carries its `similarity`
        in [0, 1].
        """
        hosted = await catalogue_shape() == "hosted"
        if hosted:
            query = hosted_top_k_sql(self.model, self.dimensions, filters)
        else:
            query = legacy_top_k_sql(filters)
        params = {"vec": _to_vector_literal(embedding), "k": k, **_filter_params(filters, hosted)}
        async with connection() as conn:
            async with conn.cursor() as cur:
                if hosted:
                    # Only the hosted shape has the HNSW index (TM11-40).
                    await cur.execute(_SET_EF_SEARCH_SQL, (str(ef_search_for(k)),))
                    if filters:
                        await cur.execute(_SET_ITERATIVE_SCAN_SQL)
                else:
                    await cur.execute(_SET_PROBES_SQL, (str(IVFFLAT_LISTS),))
                await cur.execute(query, params)
                rows = await cur.fetchall()
        return [_hosted_candidate(r) if hosted else _legacy_candidate(r) for r in rows]


def _legacy_candidate(row) -> GameCandidate:
    (game_id, title, description, genres, tags, developer,
     review_score, steam_appid, distance) = row
    return GameCandidate(
        game_id=game_id,
        title=title,
        description=description,
        genres=list(genres or []),
        tags=list(tags or []),
        developer=developer,
        review_score=review_score,
        steam_appid=steam_appid,
        similarity=_similarity(distance),
    )


def _hosted_candidate(row) -> GameCandidate:
    (game_id, title, description, genres, tags, developers,
     review_score, steam_appid, distance) = row
    return GameCandidate(
        game_id=game_id,
        title=title,
        description=description,
        genres=list(genres or []),
        tags=list(tags or []),
        developer=", ".join(developers) if developers else None,
        # Hosted scores are 0-100 integers; the candidate carries 0-1 like the
        # legacy slice, so the LLM prompt reads the same either way.
        review_score=None if review_score is None else review_score / 100,
        steam_appid=steam_appid,
        similarity=_similarity(distance),
    )
