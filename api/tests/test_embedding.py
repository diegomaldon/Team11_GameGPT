"""EmbeddingService offline (keyless) fallback tests."""

from __future__ import annotations

import math

import pytest

from api.services.embedding import (
    EMBEDDING_DIM,
    STUB_MODEL_NAME,
    EmbeddingService,
    hashed_embedding,
)


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


# ── embed_documents: the batch job's strict path (TM11-39) ──────────────────


class _Vectors(list):
    """Stands in for the numpy array SentenceTransformer.encode returns."""

    def tolist(self) -> list:
        return list(self)


class FakeModel:
    """A SentenceTransformer double: 2-dim vectors, one token per word, reads 4."""

    max_seq_length = 4

    def encode(self, texts, **kwargs):
        return _Vectors([[1.0, float(len(t))] for t in texts])

    def tokenizer(self, texts, **kwargs):
        return {"input_ids": [t.split() for t in texts]}


def _service_with(monkeypatch, load) -> EmbeddingService:
    service = EmbeddingService(model="fake/model", use_stub=False)
    monkeypatch.setattr(service, "_load", load)
    return service


@pytest.mark.asyncio
async def test_embed_documents_returns_vectors_and_token_counts(monkeypatch):
    service = _service_with(monkeypatch, FakeModel)

    out = await service.embed_documents(["one two", "a b c d e f"])

    assert [d.vector for d in out] == [[1.0, 7.0], [1.0, 11.0]]
    assert [d.token_count for d in out] == [2, 6]
    assert [d.is_truncated for d in out] == [False, True]


@pytest.mark.asyncio
async def test_embed_documents_raises_instead_of_falling_back_to_the_stub(monkeypatch):
    def broken_load():
        raise OSError("model weights missing")

    service = _service_with(monkeypatch, broken_load)

    with pytest.raises(OSError):
        await service.embed_documents(["anything"])


@pytest.mark.asyncio
async def test_embed_documents_of_nothing_is_nothing(monkeypatch):
    service = _service_with(monkeypatch, FakeModel)
    assert await service.embed_documents([]) == []


@pytest.mark.asyncio
async def test_stub_vectors_are_labelled_as_the_stub():
    """A stub run can never be mistaken for real vectors from the configured model."""
    service = EmbeddingService(model="fake/model", use_stub=True)

    out = await service.embed_documents(["relaxing builder"])

    assert service.model_name == STUB_MODEL_NAME
    assert out[0].vector == hashed_embedding("relaxing builder")
    assert out[0].token_count == 2


def test_model_name_is_the_configured_model():
    assert EmbeddingService(model="fake/model", use_stub=False).model_name == "fake/model"
