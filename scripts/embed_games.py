"""Embed the `games` table's title + description + genres into the `embedding` column.

Uses `EmbeddingService.embed_texts` (api/services/embedding.py) — a local
Hugging Face sentence-transformers model (all-MiniLM-L6-v2, 384-dim), or the
deterministic offline hashed vector when EMBEDDING_STUB=1 / torch is absent, so
this still runs end to end without a key.

Idempotent by default: only rows where `embedding is null` are processed, so
running this twice in a row does no redundant work the second time. Pass
`--all` to re-embed every row (e.g. after changing the embedding text or
switching between the offline hash and a real model).

Usage (from repo root, with the venv active):
    python scripts/embed_games.py
    python scripts/embed_games.py --all
    python scripts/embed_games.py --batch-size 16
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from tenacity import retry, stop_after_attempt, wait_exponential

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.db import connection, has_db  # noqa: E402
from api.services.embedding import EmbeddingService  # noqa: E402

DEFAULT_BATCH_SIZE = 32


def build_embedding_text(title: str, description: str | None, genres: list[str]) -> str:
    """`title + ' ' + description + ' ' + genres-joined`, per the seeding contract."""
    parts = [title or "", description or "", ", ".join(genres or [])]
    return " ".join(p for p in parts if p).strip()


async def fetch_games_to_embed(embed_all: bool) -> list[dict[str, Any]]:
    where = "" if embed_all else "where embedding is null"
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"select id, title, description, genres from games {where} order by id"
            )
            rows = await cur.fetchall()
    return [
        {"id": r[0], "title": r[1], "description": r[2], "genres": r[3] or []}
        for r in rows
    ]


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=0.5, max=8.0), reraise=True)
async def _embed_batch(service: EmbeddingService, texts: list[str]) -> list[list[float]]:
    return await service.embed_texts(texts)


async def write_embeddings(rows: list[dict[str, Any]], vectors: list[list[float]]) -> int:
    if not rows:
        return 0
    async with connection() as conn:
        async with conn.cursor() as cur:
            for row, vector in zip(rows, vectors):
                await cur.execute(
                    "update games set embedding = %s where id = %s",
                    (vector, row["id"]),
                )
        await conn.commit()
    return len(rows)


async def embed_games(embed_all: bool, batch_size: int) -> tuple[int, int]:
    """Returns (games_considered, games_embedded)."""
    rows = await fetch_games_to_embed(embed_all)
    if not rows:
        return 0, 0

    service = EmbeddingService()
    if service.offline:
        print("embed_games: EMBEDDING_STUB set - using the deterministic offline hash embedding.")
    else:
        print("embed_games: embedding locally via sentence-transformers (first run downloads the model).")

    embedded = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        texts = [build_embedding_text(r["title"], r["description"], r["genres"]) for r in batch]
        vectors = await _embed_batch(service, texts)
        embedded += await write_embeddings(batch, vectors)
        print(f"embed_games: embedded {embedded}/{len(rows)}...")

    return len(rows), embedded


async def main() -> int:
    parser = argparse.ArgumentParser(description="Embed games.title/description/genres into games.embedding.")
    parser.add_argument("--all", action="store_true", help="Re-embed every row, not just embedding IS NULL rows.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    if not has_db():
        print("embed_games: DATABASE_URL is not set - skipping (no DB to embed).")
        return 0

    considered, embedded = await embed_games(embed_all=args.all, batch_size=args.batch_size)
    if considered == 0:
        print("embed_games: nothing to do (no games need embedding; pass --all to force a re-embed, "
              "or run scripts/seed_games.py first if the games table is empty).")
    else:
        print(f"embed_games: done. {embedded}/{considered} games embedded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
