"""EmbeddingService — turns text into a 1536-dim vector.

SysML block: Embedding. Wraps OpenAI text-embedding-3-small. With no API key,
Agent B's implementation falls back to a deterministic hashed vector so the
pipeline runs offline.
"""

from __future__ import annotations

import hashlib
import math

from api.config import get_settings

EMBEDDING_DIM = 1536

_UNSET = object()


def hashed_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic, L2-normalized pseudo-embedding derived from `text`.

    Pure-Python and dependency-free so the pipeline (and re-seeding) is stable
    and reproducible offline. Same text always yields the same vector.
    """
    vec: list[float] = []
    counter = 0
    while len(vec) < dim:
        digest = hashlib.sha256(f"{text}#{counter}".encode("utf-8")).digest()
        # 32-byte digest -> four 8-byte unsigned ints -> four values in [-1, 1)
        for j in range(0, 32, 8):
            if len(vec) >= dim:
                break
            n = int.from_bytes(digest[j:j + 8], "big")
            vec.append((n / 2**64) * 2.0 - 1.0)
        counter += 1

    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        uniform = 1.0 / math.sqrt(dim)
        return [uniform] * dim
    return [x / norm for x in vec]


class EmbeddingService:
    def __init__(self, *, api_key=_UNSET, model=_UNSET) -> None:
        settings = get_settings()
        self._api_key = settings.openai_api_key if api_key is _UNSET else api_key
        self._model = settings.embedding_model if model is _UNSET else model
        self._client = None  # lazily constructed AsyncOpenAI

    @property
    def offline(self) -> bool:
        return not self._api_key

    def _openai(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string into a length-1536 vector."""
        if self.offline:
            return hashed_embedding(text)
        result = await self.embed_texts([text])
        return result[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Order-preserving."""
        if self.offline:
            return [hashed_embedding(t) for t in texts]
        if not texts:
            return []
        response = await self._openai().embeddings.create(
            model=self._model, input=texts
        )
        # Sort by index so output order matches input order regardless of API.
        ordered = sorted(response.data, key=lambda d: d.index)
        return [list(d.embedding) for d in ordered]
