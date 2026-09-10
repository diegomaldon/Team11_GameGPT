"""EmbeddingService — turns text into a vector.

SysML block: Embedding. Runs a local Hugging Face sentence-transformers model
(all-MiniLM-L6-v2, 384-dim) — free, offline, no API key. If the library isn't
installed (or `use_stub`/`EMBEDDING_STUB=1`), it falls back to a deterministic
hashed vector so tests and the pipeline still run without torch.

The model is loaded lazily and cached on the class so the ~90 MB weights load
once per process, not per request.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os

from api.config import get_settings

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

_UNSET = object()


def hashed_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic, L2-normalized pseudo-embedding derived from `text`.

    Dependency-free so the pipeline (and re-seeding) is stable and reproducible
    when the real model is unavailable. Same text always yields the same vector.
    """
    vec: list[float] = []
    counter = 0
    while len(vec) < dim:
        digest = hashlib.sha256(f"{text}#{counter}".encode("utf-8")).digest()
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
    # Cache the loaded SentenceTransformer across instances in this process.
    _shared_model = None  # type: ignore[var-annotated]

    def __init__(self, model=_UNSET, *, use_stub: bool | None = None) -> None:
        settings = get_settings()
        self._model_name = settings.embedding_model if model is _UNSET else model
        if use_stub is None:
            use_stub = os.environ.get("EMBEDDING_STUB") == "1"
        self._force_stub = bool(use_stub)

    @property
    def offline(self) -> bool:
        """True when the deterministic stub is used instead of the real model."""
        return self._force_stub

    def _load(self):
        if EmbeddingService._shared_model is None:
            from sentence_transformers import SentenceTransformer

            EmbeddingService._shared_model = SentenceTransformer(self._model_name)
        return EmbeddingService._shared_model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        arr = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return arr.tolist()

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string into a length-384 vector."""
        result = await self.embed_texts([text])
        return result[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Order-preserving."""
        if not texts:
            return []
        if self._force_stub:
            return [hashed_embedding(t) for t in texts]
        try:
            # encode() is CPU-bound; keep it off the event loop.
            return await asyncio.to_thread(self._encode, texts)
        except Exception:
            # sentence-transformers/torch unavailable or load failed → stub.
            return [hashed_embedding(t) for t in texts]
