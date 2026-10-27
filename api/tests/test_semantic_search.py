"""POST /api/search (TM11-42, TM11-43, REQ011).

One group per acceptance criterion. The embedding model and the vector store
are faked, so these run offline with no torch and no database. Latency on the
real model and catalogue is measured by scripts/eval_search_latency.py.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.models import GameCandidate
from api.routers import search as search_router
from api.services.embedding import EmbeddedText, EmbeddingService
from api.services.semantic_search import SemanticSearchService
from api.services.vector_store import SearchFilters

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _game(title: str, similarity: float, **extra) -> GameCandidate:
    return GameCandidate(game_id=uuid4(), title=title, similarity=similarity, **extra)


CATALOGUE = [
    _game("Stardew Valley", 0.81, genres=["Simulation", "RPG"], steam_appid=413150,
          review_score=0.98),
    _game("My Time at Portia", 0.74, genres=["Simulation"]),
    _game("Dinkum", 0.69),
    _game("Factorio", 0.31),
    _game("Counter-Strike 2", 0.12),
]


class FakeEmbedding:
    model_name = MODEL

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[EmbeddedText]:
        self.queries.extend(texts)
        return [EmbeddedText([0.0] * 384, len(t.split()), False) for t in texts]


class FakeVectorStore:
    model = MODEL

    def __init__(self, candidates=CATALOGUE, error: Exception | None = None) -> None:
        self.candidates = candidates
        self.error = error
        self.calls: list[int] = []
        self.filters: list[SearchFilters | None] = []

    async def top_k(self, embedding, k=20, filters=None):
        self.calls.append(k)
        self.filters.append(filters)
        if self.error:
            raise self.error
        return self.candidates[:k]


@pytest.fixture
def fakes(monkeypatch):
    embedding, store = FakeEmbedding(), FakeVectorStore()

    def build():
        return SemanticSearchService(embedding, store)

    monkeypatch.setattr(search_router, "SemanticSearchService", build)
    return embedding, store


@pytest.fixture
def client(fakes) -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _search(client: TestClient, **body):
    return client.post("/api/search", json={"query": "cozy farming game", **body})


# AC: accepts query text and returns ranked candidates with scores.

def test_returns_ranked_candidates_with_scores(client):
    resp = _search(client)

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert [r["rank"] for r in results] == [1, 2, 3, 4, 5]
    assert [r["title"] for r in results][:3] == ["Stardew Valley", "My Time at Portia", "Dinkum"]
    scores = [r["similarity"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 1 for s in scores)


def test_result_carries_catalogue_fields(client):
    top = _search(client).json()["results"][0]

    assert top["genres"] == ["Simulation", "RPG"]
    assert top["steam_appid"] == 413150
    assert top["review_score"] == 0.98
    assert set(top) == {"rank", "game_id", "title", "similarity", "genres",
                        "steam_appid", "review_score"}


def test_embeds_the_trimmed_query(client, fakes):
    embedding, _ = fakes

    body = _search(client, query="  cozy farming game  ").json()

    assert embedding.queries == ["cozy farming game"]
    assert body["query"] == "cozy farming game"


def test_ranks_by_similarity_even_if_store_order_is_off(monkeypatch):
    shuffled = [CATALOGUE[2], CATALOGUE[0], CATALOGUE[1]]
    store = FakeVectorStore(candidates=shuffled)
    monkeypatch.setattr(search_router, "SemanticSearchService",
                        lambda: SemanticSearchService(FakeEmbedding(), store))
    client = TestClient(create_app())

    titles = [r["title"] for r in _search(client).json()["results"]]

    assert titles == ["Stardew Valley", "My Time at Portia", "Dinkum"]


def test_reports_model_and_server_time(client):
    body = _search(client).json()

    assert body["model"] == MODEL
    assert body["took_ms"] >= 0


# AC: top-k configurable.

def test_k_defaults_to_10(client, fakes):
    _, store = fakes

    body = _search(client).json()

    assert store.calls == [10]
    assert body["k"] == 10


@pytest.mark.parametrize("k", [1, 3, 50])
def test_k_is_passed_to_the_vector_store(client, fakes, k):
    _, store = fakes

    body = _search(client, k=k).json()

    assert store.calls == [k]
    assert len(body["results"]) == min(k, len(CATALOGUE))


@pytest.mark.parametrize("k", [0, -1, 51])
def test_k_out_of_range_is_rejected(client, fakes, k):
    _, store = fakes

    resp = _search(client, k=k)

    assert resp.status_code == 422
    assert store.calls == []


# Input validation.

@pytest.mark.parametrize("query", ["", "   ", "x" * 501])
def test_blank_or_too_long_query_is_rejected(client, fakes, query):
    embedding, _ = fakes

    resp = client.post("/api/search", json={"query": query})

    assert resp.status_code == 422
    assert embedding.queries == []


def test_empty_catalogue_returns_no_results(monkeypatch):
    monkeypatch.setattr(search_router, "SemanticSearchService",
                        lambda: SemanticSearchService(FakeEmbedding(), FakeVectorStore([])))
    client = TestClient(create_app())

    resp = _search(client)

    assert resp.status_code == 200
    assert resp.json()["results"] == []


# TM11-43: platform and genre filters.

def test_no_filters_by_default(client, fakes):
    _, store = fakes

    _search(client)

    assert store.filters == [SearchFilters()]


def test_filters_reach_the_vector_store(client, fakes):
    _, store = fakes

    resp = _search(client, platforms=["steam", "xbox"], genres=["RPG", " Co-op "])

    assert resp.status_code == 200
    assert store.filters == [SearchFilters(platforms=("steam", "xbox"), genres=("RPG", "Co-op"))]


def test_repeated_filter_values_are_sent_once(client, fakes):
    _, store = fakes

    _search(client, platforms=["epic", "epic"], genres=["RPG", "rpg", "Puzzle"])

    assert store.filters == [SearchFilters(platforms=("epic",), genres=("RPG", "Puzzle"))]


@pytest.mark.parametrize("body", [
    {"platforms": ["playstation"]},
    {"platforms": "steam"},
    {"genres": [""]},
    {"genres": ["   "]},
    {"genres": ["x" * 51]},
    {"genres": [f"genre {n}" for n in range(11)]},
])
def test_bad_filters_are_rejected(client, fakes, body):
    _, store = fakes

    resp = _search(client, **body)

    assert resp.status_code == 422
    assert store.calls == []


def test_a_filter_nothing_matches_is_a_200_with_no_results(monkeypatch):
    monkeypatch.setattr(search_router, "SemanticSearchService",
                        lambda: SemanticSearchService(FakeEmbedding(), FakeVectorStore([])))
    client = TestClient(create_app())

    resp = _search(client, platforms=["epic"], genres=["Visual Novel"])

    assert resp.status_code == 200
    assert resp.json()["results"] == []


def test_the_response_echoes_the_filters_it_applied(client):
    body = _search(client, platforms=["xbox"], genres=["RPG", "rpg"]).json()

    assert body["platforms"] == ["xbox"]
    assert body["genres"] == ["RPG"]


# Failures.

def test_store_failure_is_a_structured_503_without_the_cause(monkeypatch):
    store = FakeVectorStore(error=RuntimeError("connection to db.secret-host refused"))
    monkeypatch.setattr(search_router, "SemanticSearchService",
                        lambda: SemanticSearchService(FakeEmbedding(), store))
    client = TestClient(create_app(), raise_server_exceptions=False)

    resp = _search(client)

    assert resp.status_code == 503
    assert resp.json()["detail"] == {
        "error": "search_failed",
        "message": search_router.SEARCH_FAILED_MESSAGE,
    }
    assert "secret-host" not in resp.text


def test_model_load_failure_is_a_503_not_stub_results(monkeypatch):
    # The real service, with a model that can't load (no torch, failed
    # download, out of memory). It must not fall back to hashed vectors.
    def fail_to_load(self):
        raise OSError("can't load weights from /models/secret-path")

    monkeypatch.setattr(EmbeddingService, "_load", fail_to_load)
    store = FakeVectorStore()
    monkeypatch.setattr(
        search_router, "SemanticSearchService",
        lambda: SemanticSearchService(EmbeddingService(MODEL, use_stub=False), store),
    )
    client = TestClient(create_app(), raise_server_exceptions=False)

    resp = _search(client)

    assert resp.status_code == 503
    assert resp.json()["detail"] == {
        "error": "search_failed",
        "message": search_router.SEARCH_FAILED_MESSAGE,
    }
    assert "secret-path" not in resp.text
    assert store.calls == []


# Wiring.

def test_vector_store_searches_with_the_query_model():
    embedding = FakeEmbedding()
    embedding.model_name = "some/other-model"

    service = SemanticSearchService(embedding)

    assert service.vector_store.model == "some/other-model"


# AC: contract documented.

def test_endpoint_is_in_the_openapi_contract():
    spec = TestClient(create_app()).get("/openapi.json").json()

    operation = spec["paths"]["/api/search"]["post"]
    assert "200" in operation["responses"]
    assert "SemanticSearchResponse" in spec["components"]["schemas"]
    request = spec["components"]["schemas"]["SemanticSearchRequest"]["properties"]
    assert {"platforms", "genres"} <= set(request)
