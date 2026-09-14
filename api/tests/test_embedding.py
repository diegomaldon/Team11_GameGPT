"""EmbeddingService offline (keyless) fallback tests."""

from __future__ import annotations

import math

import pytest

from api.services.embedding import EMBEDDING_DIM, EmbeddingService, hashed_embedding


def test_hashed_embedding_length_and_normalized():
    vec = hashed_embedding("a chill game for a podcast night")
    assert len(vec) == EMBEDDING_DIM
    norm = math.sqrt(sum(x * x for x in vec))
    assert norm == pytest.approx(1.0, abs=1e-9)


def test_hashed_embedding_is_deterministic():
    a = hashed_embedding("same text")
    b = hashed_embedding("same text")
    assert a == b
    assert hashed_embedding("different") != a


@pytest.mark.asyncio
async def test_embed_query_stub_length():
    service = EmbeddingService(use_stub=True)
    assert service.offline is True
    vec = await service.embed_query("relaxing builder")
    assert len(vec) == EMBEDDING_DIM


@pytest.mark.asyncio
async def test_embed_texts_stub_order_preserving():
    service = EmbeddingService(use_stub=True)
    texts = ["one", "two", "three"]
    out = await service.embed_texts(texts)
    assert len(out) == 3
    assert all(len(v) == EMBEDDING_DIM for v in out)
    # Order-preserving and content-addressed: each row matches its text.
    for text, vec in zip(texts, out):
        assert vec == hashed_embedding(text)
    assert await service.embed_texts([]) == []
