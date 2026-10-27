"""EmbeddingPipeline: embed the whole catalogue in batches (TM11-39, REQ011).

The DB and the model are faked, so this runs offline with no DATABASE_URL.
FakeCatalogue behaves like public.game_embeddings: one row per (game, model).
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
from uuid import uuid4

import pytest

from api.db import repositories
from api.services import embedding_pipeline
from api.services.embedding import EmbeddedText, EmbeddingModelError
from api.services.embedding_pipeline import EmbeddingPipeline
from api.services.game_document import TEMPLATE_VERSION, build_game_document

pytestmark = pytest.mark.asyncio

MODEL = "fake/model"


def make_game(title: str) -> dict:
    return {
        "game_id": uuid4(),
        "title": title,
        "description": f"{title} is a game.",
        "genres": ["Indie", "Action"],
        "tags": ["Roguelike"],
    }


class FakeCatalogue:
    def __init__(self, games: list[dict]) -> None:
        self.games = games
        self.rows: dict = {}  # (game_id, model) -> GameEmbedding
        self.writes_to_fail = 0

    async def list_games_with_document_hash(self, model):
        listed = []
        for g in self.games:
            row = self.rows.get((g["game_id"], model))
            listed.append({
                **g,
                "document_hash": getattr(row, "document_hash", None),
                "template_version": getattr(row, "template_version", None),
            })
        return listed

    async def upsert_game_embeddings(self, rows):
        if self.writes_to_fail:
            self.writes_to_fail -= 1
            raise ConnectionError("db went away")
        for row in rows:
            self.rows[(row.game_id, row.model)] = row

    async def count_game_embeddings(self, model):
        return len(self.games), sum(1 for (_, m) in self.rows if m == model)


class FakeEmbedder:
    """2-dim vectors, one token per word, reads 20 words. Fails on demand."""

    model_name = MODEL

    def __init__(self, *, failures_before_success: int = 0, poison: str | None = None) -> None:
        self.failures_left = failures_before_success
        self.poison = poison
        self.batches: list[list[str]] = []

    async def embed_documents(self, texts):
        self.batches.append(list(texts))
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("model hiccup")
        if self.poison and any(self.poison in t for t in texts):
            raise RuntimeError("this batch always fails")
        return [EmbeddedText([0.6, 0.8], len(t.split()), len(t.split()) > 20) for t in texts]


@pytest.fixture
def catalogue(monkeypatch):
    fake = FakeCatalogue([make_game(f"Game {n}") for n in range(7)])
    monkeypatch.setattr(
        repositories, "list_games_with_document_hash", fake.list_games_with_document_hash
    )
    monkeypatch.setattr(repositories, "upsert_game_embeddings", fake.upsert_game_embeddings)
    monkeypatch.setattr(repositories, "count_game_embeddings", fake.count_game_embeddings)
    monkeypatch.setattr(embedding_pipeline, "RETRY_WAIT_SECONDS", 0)
    return fake


# ── AC: embeddings generated in batches with retry and token cost logging ────


async def test_embeds_every_game_in_batches(catalogue):
    embedder = FakeEmbedder()

    report = await EmbeddingPipeline(embedder, batch_size=3).run()

    assert [len(b) for b in embedder.batches] == [3, 3, 1]
    assert report.embedded_count == 7
    assert report.batch_count == 3


async def test_a_batch_that_fails_once_is_retried(catalogue):
    embedder = FakeEmbedder(failures_before_success=2)

    report = await EmbeddingPipeline(embedder, batch_size=10).run()

    assert len(embedder.batches) == 3  # two failures, then success
    assert report.embedded_count == 7
    assert report.failed_game_ids == []


async def test_a_batch_that_keeps_failing_is_skipped_and_reported(catalogue):
    embedder = FakeEmbedder(poison="Game 4")

    report = await EmbeddingPipeline(embedder, batch_size=3).run()

    failed = {g["game_id"] for g in catalogue.games[3:6]}
    assert set(report.failed_game_ids) == failed
    assert report.embedded_count == 4  # batches 1 and 3 still saved
    assert not report.is_complete


async def test_a_model_that_drops_a_vector_fails_the_batch_instead_of_misaligning(catalogue):
    class DropsOne(FakeEmbedder):
        async def embed_documents(self, texts):
            return (await super().embed_documents(texts))[:-1]

    report = await EmbeddingPipeline(DropsOne(), batch_size=7).run()

    assert len(report.failed_game_ids) == 7
    assert catalogue.rows == {}


async def test_a_model_that_cannot_load_stops_the_run_without_retrying(catalogue):
    class CannotLoad(FakeEmbedder):
        async def embed_documents(self, texts):
            self.batches.append(list(texts))
            raise EmbeddingModelError("could not load fake/model")

    embedder = CannotLoad()

    with pytest.raises(EmbeddingModelError):
        await EmbeddingPipeline(embedder, batch_size=3).run()
    assert len(embedder.batches) == 1  # not 3 batches x 3 attempts
    assert catalogue.rows == {}


async def test_a_failed_write_is_reported_and_the_run_goes_on(catalogue):
    catalogue.writes_to_fail = 1

    report = await EmbeddingPipeline(FakeEmbedder(), batch_size=3).run()

    assert set(report.failed_game_ids) == {g["game_id"] for g in catalogue.games[:3]}
    assert report.embedded_count == 4


async def test_tokens_and_cost_are_totalled_and_logged(catalogue, caplog):
    caplog.set_level(logging.INFO, logger="gamegpt.embedding_pipeline")

    report = await EmbeddingPipeline(FakeEmbedder(), batch_size=4).run()

    words_per_game = len(build_game_document(catalogue.games[0]).split())
    assert report.token_count == 7 * words_per_game
    assert "tokens" in caplog.text and "cost" in caplog.text


async def test_cost_of_the_local_model_is_zero(catalogue):
    embedder = FakeEmbedder()
    embedder.model_name = "sentence-transformers/all-MiniLM-L6-v2"

    report = await EmbeddingPipeline(embedder).run()

    assert report.estimated_cost_usd == 0.0


async def test_a_run_with_nothing_to_do_still_costs_zero_not_unknown(catalogue):
    embedder = FakeEmbedder()
    embedder.model_name = "sentence-transformers/all-MiniLM-L6-v2"
    await EmbeddingPipeline(embedder).run()

    report = await EmbeddingPipeline(embedder).run()

    assert report.embedded_count == 0
    assert report.estimated_cost_usd == 0.0
    assert report.to_dict()["estimated_cost_usd"] == 0.0


async def test_cost_of_an_unknown_model_is_unknown_not_zero(catalogue):
    report = await EmbeddingPipeline(FakeEmbedder()).run()
    assert report.estimated_cost_usd is None


async def test_documents_the_model_cut_short_are_counted(catalogue):
    catalogue.games[0]["description"] = "a very long description " * 5

    report = await EmbeddingPipeline(FakeEmbedder()).run()

    assert report.truncated_count == 1


# ── AC: model name and dimensions recorded per row ──────────────────────────


async def test_every_row_records_model_dimensions_and_document_hash(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()

    game = catalogue.games[0]
    row = catalogue.rows[(game["game_id"], MODEL)]
    document = build_game_document(game)
    assert row.model == MODEL
    assert row.dimensions == 2 == len(row.embedding)
    assert row.document_hash == hashlib.sha256(document.encode("utf-8")).hexdigest()
    assert row.token_count == len(document.split())


# ── AC: resumable after failure ─────────────────────────────────────────────


async def test_a_rerun_only_embeds_what_the_last_run_missed(catalogue):
    await EmbeddingPipeline(FakeEmbedder(poison="Game 4"), batch_size=3).run()
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second, batch_size=3).run()

    assert second.batches == [[build_game_document(g) for g in catalogue.games[3:6]]]
    assert report.games_to_embed == 3
    assert report.is_complete


async def test_a_rerun_with_nothing_missing_does_no_work(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run()

    assert second.batches == []
    assert report.embedded_count == 0
    assert report.is_complete


async def test_re_embed_all_rewrites_every_row_without_duplicates(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run(re_embed_all=True)

    assert report.embedded_count == 7
    assert len(catalogue.rows) == 7


# ── AC: full corpus embedded and counted ────────────────────────────────────


async def test_the_report_counts_the_whole_catalogue(catalogue):
    report = await EmbeddingPipeline(FakeEmbedder()).run()

    assert report.catalogue_count == 7
    assert report.embedded_total == 7
    assert report.is_complete


async def test_report_serialises_to_plain_json_types(catalogue):
    report = await EmbeddingPipeline(FakeEmbedder(poison="Game 0")).run()

    data = report.to_dict()

    assert data["model"] == MODEL
    assert all(isinstance(game_id, str) for game_id in data["failed_game_ids"])
    assert data["is_complete"] is False


# ── settings ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("batch_size", [0, -1])
async def test_batch_size_must_be_positive(batch_size):
    with pytest.raises(ValueError):
        EmbeddingPipeline(FakeEmbedder(), batch_size=batch_size)


# ── TM11-41: re-embed only changed games ────────────────────────────────────


async def test_every_row_has_a_content_hash_of_its_document(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()

    for game in catalogue.games:
        row = catalogue.rows[(game["game_id"], MODEL)]
        assert row.document_hash == embedding_pipeline.document_hash(build_game_document(game))


async def test_a_rerun_skips_every_unchanged_game(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run()

    assert second.batches == []
    assert report.unchanged_skipped == 7
    assert report.new_count == report.changed_count == 0


async def test_a_rerun_with_one_modified_game_embeds_only_that_game(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    modified = catalogue.games[2]
    old_hash = catalogue.rows[(modified["game_id"], MODEL)].document_hash
    modified["description"] = "Now a cozy farming game."
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run()

    assert second.batches == [[build_game_document(modified)]]
    assert (report.changed_count, report.unchanged_skipped, report.new_count) == (1, 6, 0)
    assert report.embedded_count == 1
    new_row = catalogue.rows[(modified["game_id"], MODEL)]
    assert new_row.document_hash != old_hash
    assert new_row.document_hash == embedding_pipeline.document_hash(build_game_document(modified))
    assert report.is_complete


async def test_a_change_to_a_field_that_is_not_embedded_is_not_a_change(catalogue):
    """Only the document's fields count, so editing anything else costs nothing."""
    await EmbeddingPipeline(FakeEmbedder()).run()
    catalogue.games[0]["critic_score"] = 91
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run()

    assert second.batches == []
    assert report.unchanged_skipped == 7


async def test_a_change_to_tags_is_a_change(catalogue):
    """Tags are part of the document since template v1 (TM11-38)."""
    await EmbeddingPipeline(FakeEmbedder()).run()
    catalogue.games[0]["tags"] = ["Cozy", "Farming"]
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run()

    assert second.batches == [[build_game_document(catalogue.games[0])]]
    assert report.changed_count == 1


async def test_new_and_changed_games_are_counted_separately(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    catalogue.games[0]["title"] = "Game 0: Remastered"
    catalogue.games.append(make_game("Brand New Game"))

    report = await EmbeddingPipeline(FakeEmbedder()).run()

    assert (report.new_count, report.changed_count, report.unchanged_skipped) == (1, 1, 6)
    assert report.embedded_count == 2


async def test_re_embed_all_ignores_unchanged_hashes(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run(re_embed_all=True)

    assert sum(len(b) for b in second.batches) == 7
    assert report.unchanged_skipped == 0


async def test_a_changed_game_whose_batch_fails_is_retried_next_run(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()
    catalogue.games[4]["description"] = "Rewritten."
    first = await EmbeddingPipeline(FakeEmbedder(poison="Rewritten.")).run()
    assert first.failed_game_ids == [catalogue.games[4]["game_id"]]

    report = await EmbeddingPipeline(FakeEmbedder()).run()

    assert report.changed_count == 1  # the old hash is still stored, so it is still changed
    assert report.embedded_count == 1


async def test_the_report_carries_the_skip_counts(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()

    data = (await EmbeddingPipeline(FakeEmbedder()).run()).to_dict()

    assert data["unchanged_skipped"] == 7
    assert data["changed_count"] == 0 and data["new_count"] == 0


# ── TM11-38: template versioned so re-embedding is traceable ────────────────


async def test_every_row_records_the_template_version(catalogue):
    await EmbeddingPipeline(FakeEmbedder()).run()

    assert {row.template_version for row in catalogue.rows.values()} == {TEMPLATE_VERSION}


async def test_the_report_records_the_template_version(catalogue):
    data = (await EmbeddingPipeline(FakeEmbedder()).run()).to_dict()

    assert data["template_version"] == TEMPLATE_VERSION


async def test_rows_from_an_older_template_are_re_embedded_as_changed(catalogue):
    """Even when the text hashes the same, an older version means an older template."""
    await EmbeddingPipeline(FakeEmbedder()).run()
    old = catalogue.games[1]
    key = (old["game_id"], MODEL)
    catalogue.rows[key] = dataclasses.replace(catalogue.rows[key], template_version="v0")
    second = FakeEmbedder()

    report = await EmbeddingPipeline(second).run()

    assert second.batches == [[build_game_document(old)]]
    assert (report.changed_count, report.unchanged_skipped) == (1, 6)
    assert catalogue.rows[key].template_version == TEMPLATE_VERSION
