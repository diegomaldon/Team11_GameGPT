"""VectorStore — semantic top-k over the games knowledge base.

SysML block: Vector Store. pgvector cosine similarity; k defaults to 20.
The interface is deliberately narrow so pgvector can later be swapped for a
managed vector DB without touching callers.
"""

from __future__ import annotations

from api.db import connection
from api.models import GameCandidate


def _to_vector_literal(embedding: list[float]) -> str:
    """Render an embedding as a pgvector text literal: '[0.1,0.2,...]'.

    Cast to ::vector in SQL so the query works whether or not the pgvector
    psycopg adapter registered.
    """
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class VectorStore:
    async def top_k(self, embedding: list[float], k: int = 20) -> list[GameCandidate]:
        """Return up to `k` games most similar to `embedding`, cosine-ranked.

        Each candidate carries its `similarity` in [0, 1].
        """
        vec = _to_vector_literal(embedding)
        sql = (
            "select id, title, description, genres, tags, developer, "
            "review_score, steam_appid, (embedding <=> %s::vector) as distance "
            "from games "
            "where embedding is not null "
            "order by distance asc "
            "limit %s"
        )
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (vec, k))
                rows = await cur.fetchall()

        candidates: list[GameCandidate] = []
        for row in rows:
            (game_id, title, description, genres, tags, developer,
             review_score, steam_appid, distance) = row
            similarity = 1.0 - float(distance)
            # Clamp: floating error / non-normalized vectors can nudge outside [0, 1].
            similarity = max(0.0, min(1.0, similarity))
            candidates.append(
                GameCandidate(
                    game_id=game_id,
                    title=title,
                    description=description,
                    genres=list(genres or []),
                    tags=list(tags or []),
                    developer=developer,
                    review_score=review_score,
                    steam_appid=steam_appid,
                    similarity=similarity,
                )
            )
        return candidates
