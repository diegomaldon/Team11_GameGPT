"""VectorStore + DeduplicationService tests.

Pure helpers run always; anything that touches Postgres skips when no DB is
configured, so the suite is green offline.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from api.db import has_db
from api.services.deduplication import DeduplicationService, normalize_title
from api.services.vector_store import _to_vector_literal

DEV_USER = UUID("00000000-0000-0000-0000-000000000001")


def test_normalize_title_lowercases_strips_punct_collapses_ws():
    assert normalize_title("  The   Witcher 3: Wild-Hunt!! ") == "the witcher 3 wild hunt"
    assert normalize_title("HALF-LIFE 2") == "half life 2"
    assert normalize_title(None) == ""
    assert normalize_title("") == ""


def test_vector_literal_format():
    assert _to_vector_literal([1.0, 2.5, -3.0]).startswith("[")
    assert _to_vector_literal([1.0, 2.5, -3.0]).endswith("]")
    assert _to_vector_literal([]) == "[]"


@pytest.mark.asyncio
async def test_vector_store_top_k_requires_db(candidates):
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    from api.services.vector_store import VectorStore

    store = VectorStore()
    results = await store.top_k([0.0] * 1536, k=5)
    assert len(results) <= 5
    for r in results:
        assert r.similarity is None or 0.0 <= r.similarity <= 1.0


@pytest.mark.asyncio
async def test_dedup_filter_owned_requires_db(candidates):
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    dedup = DeduplicationService()
    kept = await dedup.filter_owned(DEV_USER, candidates)
    assert len(kept) <= len(candidates)
