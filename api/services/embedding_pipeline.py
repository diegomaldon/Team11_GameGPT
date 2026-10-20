"""EmbeddingPipeline: embed the whole games catalogue in batches (TM11-39, REQ011).

  run  find games with no vector from this model yet, or whose text changed
       since it was embedded, embed them a batch at a time, and store one
       public.game_embeddings row per game.

Each batch is saved as soon as it is embedded, so a run that stops halfway
loses nothing: the next run only picks up games that still need a vector. A
batch is retried before it counts as failed. A failed batch is skipped and its
games reported, and the rest of the catalogue still gets embedded. A model that
can't load stops the run at once, since every batch would fail the same way.

Every row records the model, the vector's dimensions, a SHA-256 of the exact
text embedded and its token count. On the next run, a game whose text still
hashes the same is skipped (TM11-41), so a catalogue update only pays for the
games it touched. Token totals and cost are logged per batch. Logs carry
counts only.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID

from tenacity import (
    AsyncRetrying,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from api.db import repositories
from api.services.embedding import STUB_MODEL_NAME, EmbeddedText, EmbeddingModelError

log = logging.getLogger("gamegpt.embedding_pipeline")

DEFAULT_BATCH_SIZE = 32
EMBED_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 1.0

# USD per million tokens. A local model costs nothing to run. An unknown model
# reports its cost as unknown rather than guessing.
PRICE_PER_MILLION_TOKENS_USD = {
    "sentence-transformers/all-MiniLM-L6-v2": 0.0,
    STUB_MODEL_NAME: 0.0,
}


class Embedder(Protocol):
    model_name: str

    async def embed_documents(self, texts: list[str]) -> list[EmbeddedText]: ...


@dataclass(frozen=True)
class GameEmbedding:
    """One public.game_embeddings row."""

    game_id: UUID
    model: str
    dimensions: int
    embedding: list[float]
    document_hash: str
    token_count: int


@dataclass
class EmbeddingRunReport:
    model: str
    games_to_embed: int = 0
    new_count: int = 0  # games with no vector from this model before the run
    changed_count: int = 0  # games whose text no longer matches the stored hash
    unchanged_skipped: int = 0  # games whose text matches; not re-embedded
    embedded_count: int = 0
    failed_game_ids: list[UUID] = field(default_factory=list)
    batch_count: int = 0
    token_count: int = 0
    truncated_count: int = 0
    catalogue_count: int = 0
    embedded_total: int = 0  # games with a vector from this model, after the run
    duration_seconds: float = 0.0

    @property
    def is_complete(self) -> bool:
        return not self.failed_game_ids and self.embedded_total == self.catalogue_count

    @property
    def estimated_cost_usd(self) -> float | None:
        """Cost of the tokens embedded so far. None when the model's price is unknown."""
        price = PRICE_PER_MILLION_TOKENS_USD.get(self.model)
        if price is None:
            return None
        return round(self.token_count / 1_000_000 * price, 6)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["failed_game_ids"] = [str(game_id) for game_id in self.failed_game_ids]
        data["estimated_cost_usd"] = self.estimated_cost_usd
        data["is_complete"] = self.is_complete
        return data


def document_hash(document: str) -> str:
    """SHA-256 hex of the exact text embedded, as stored in document_hash."""
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def build_game_document(game: Mapping[str, Any]) -> str:
    """The text embedded for a game: title, description, then genres.

    The same text embed_games.py has always used. TM11-38 replaces it with a
    documented, versioned template.
    """
    parts = [game["title"], game.get("description") or "", ", ".join(game.get("genres") or [])]
    return " ".join(part for part in parts if part)


class EmbeddingPipeline:
    def __init__(self, embedder: Embedder, *, batch_size: int = DEFAULT_BATCH_SIZE) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._embedder = embedder
        self._batch_size = batch_size

    async def run(self, *, re_embed_all: bool = False) -> EmbeddingRunReport:
        """Embed games that are new or changed for this model, or all of them."""
        started_at = time.monotonic()
        model = self._embedder.model_name
        report = EmbeddingRunReport(model=model)

        games = select_games_to_embed(
            await repositories.list_games_with_document_hash(model), report,
            re_embed_all=re_embed_all,
        )
        report.games_to_embed = len(games)
        batches = [
            games[start:start + self._batch_size]
            for start in range(0, len(games), self._batch_size)
        ]
        log.info(
            "embedding %d games (%d new, %d changed, %d unchanged skipped) in %d batches with %s",
            len(games), report.new_count, report.changed_count, report.unchanged_skipped,
            len(batches), model,
        )

        for number, batch in enumerate(batches, start=1):
            await self._process_batch(batch, report)
            report.batch_count += 1
            log.info(
                "batch %d/%d: %d embedded, %d failed, %d tokens, cost %s",
                number, len(batches), report.embedded_count, len(report.failed_game_ids),
                report.token_count, format_cost_usd(report.estimated_cost_usd),
            )

        report.catalogue_count, report.embedded_total = (
            await repositories.count_game_embeddings(model)
        )
        report.duration_seconds = round(time.monotonic() - started_at, 2)
        log.info(
            "embedding run done: %d of %d games have a vector from %s",
            report.embedded_total, report.catalogue_count, model,
        )
        return report

    async def _process_batch(
        self, games: Sequence[Mapping[str, Any]], report: EmbeddingRunReport
    ) -> None:
        documents = [build_game_document(game) for game in games]
        try:
            embedded = await self._embed_with_retry(documents)
            rows = [
                _to_row(game, document, result, self._embedder.model_name)
                for game, document, result in zip(games, documents, embedded, strict=True)
            ]
            await repositories.upsert_game_embeddings(rows)
        except EmbeddingModelError:
            raise
        except Exception:
            log.exception("batch of %d games failed; they are left for the next run", len(games))
            report.failed_game_ids.extend(game["game_id"] for game in games)
            return

        report.embedded_count += len(rows)
        report.token_count += sum(row.token_count for row in rows)
        report.truncated_count += sum(1 for result in embedded if result.is_truncated)

    async def _embed_with_retry(self, documents: list[str]) -> list[EmbeddedText]:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(EMBED_ATTEMPTS),
            retry=retry_if_not_exception_type(EmbeddingModelError),
            wait=wait_exponential(multiplier=RETRY_WAIT_SECONDS, max=10 * RETRY_WAIT_SECONDS),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._embedder.embed_documents(documents)


def _to_row(
    game: Mapping[str, Any], document: str, result: EmbeddedText, model: str
) -> GameEmbedding:
    return GameEmbedding(
        game_id=game["game_id"],
        model=model,
        dimensions=len(result.vector),
        embedding=result.vector,
        document_hash=document_hash(document),
        token_count=result.token_count,
    )


def select_games_to_embed(
    games: Sequence[Mapping[str, Any]], report: EmbeddingRunReport, *, re_embed_all: bool
) -> list[Mapping[str, Any]]:
    """Keep the games that need a vector, and count why on the report.

    A game needs one when it has no vector from this model yet, or when the
    text it would be embedded from no longer hashes to the stored value.
    `re_embed_all` keeps every game, for a new document template or model.
    """
    selected = []
    for game in games:
        stored = game.get("document_hash")
        if stored is None:
            report.new_count += 1
        elif stored != document_hash(build_game_document(game)):
            report.changed_count += 1
        elif not re_embed_all:
            report.unchanged_skipped += 1
            continue
        selected.append(game)
    return selected


def format_cost_usd(cost_usd: float | None) -> str:
    return "unknown" if cost_usd is None else f"${cost_usd:.4f}"
