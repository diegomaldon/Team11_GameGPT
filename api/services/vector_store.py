"""VectorStore — semantic top-k over the games knowledge base.

SysML block: Vector Store. pgvector cosine similarity; k defaults to 20.
The interface is deliberately narrow so pgvector can later be swapped for a
managed vector DB without touching callers.

Reads whichever shape DATABASE_URL has (api/db/schema.py):

  hosted  public.game_embeddings joined to public.games, filtered to this
          service's model and cast to its size, so the partial HNSW index from
          20261018120000_game_embeddings_hnsw_index.sql serves it (TM11-40)
  legacy  games.embedding on the local 0001_init.sql slice
"""

from __future__ import annotations

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


_LEGACY_SQL = sql.SQL(
    "select id, title, description, genres, tags, developer, "
    "review_score, steam_appid, (embedding <=> %s::vector) as distance "
    "from games "
    "where embedding is not null "
    "order by distance asc "
    "limit %s"
)


def hosted_top_k_sql(model: str, dimensions: int) -> sql.Composed:
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
    return sql.SQL(
        "select g.game_id, g.title, g.description, g.genres, g.tags, g.developers, "
        "g.review_score, g.steam_appid, {distance} as distance "
        "from public.game_embeddings e "
        "join public.games g on g.game_id = e.game_id "
        "where e.model = {model} "
        "order by {distance} "
        "limit %(k)s"
    ).format(distance=distance, model=sql.Literal(model))


# pgvector's default hnsw.ef_search. An HNSW scan returns at most this many
# rows, so a larger k needs a larger search list or it comes back short.
HNSW_DEFAULT_EF_SEARCH = 40

# Transaction-local, so it lasts only for this search. The connection is
# autocommit-off, so the select below runs in the same transaction.
_SET_EF_SEARCH_SQL = sql.SQL("select set_config('hnsw.ef_search', %s, true)")


def ef_search_for(k: int) -> int:
    """The HNSW search list size that lets a scan return all `k` rows."""
    return max(k, HNSW_DEFAULT_EF_SEARCH)


def _similarity(distance: float) -> float:
    # Clamp: floating error / non-normalized vectors can nudge outside [0, 1].
    return max(0.0, min(1.0, 1.0 - float(distance)))


class VectorStore:
    def __init__(self, model: str | None = None, dimensions: int = EMBEDDING_DIM) -> None:
        self.model = model or get_settings().embedding_model
        self.dimensions = dimensions

    async def top_k(self, embedding: list[float], k: int = 20) -> list[GameCandidate]:
        """Return up to `k` games most similar to `embedding`, cosine-ranked.

        Each candidate carries its `similarity` in [0, 1].
        """
        vec = _to_vector_literal(embedding)
        hosted = await catalogue_shape() == "hosted"
        if hosted:
            query, params = hosted_top_k_sql(self.model, self.dimensions), {"vec": vec, "k": k}
        else:
            query, params = _LEGACY_SQL, (vec, k)
        async with connection() as conn:
            async with conn.cursor() as cur:
                if hosted:
                    # Only the hosted shape has the HNSW index (TM11-40); the
                    # legacy slice uses IVFFlat, which ignores this setting.
                    await cur.execute(_SET_EF_SEARCH_SQL, (str(ef_search_for(k)),))
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
