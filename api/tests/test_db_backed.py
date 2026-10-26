"""VectorStore + DeduplicationService tests.

Pure helpers run always; anything that touches Postgres skips when no DB is
configured, so the suite is green offline.
"""

from __future__ import annotations

from uuid import UUID

import psycopg
import pytest

from api.db import connection, has_db
from api.services.embedding import EMBEDDING_DIM
from api.services.deduplication import DeduplicationService
from api.services.title_matching import ownership_key
from api.services.vector_store import _to_vector_literal

DEV_USER = UUID("00000000-0000-0000-0000-000000000001")


async def _require_db() -> None:
    """Skip unless a Postgres is actually reachable (not just configured).

    `.env` may set DATABASE_URL to a remote DB that isn't up in this
    environment; skip cleanly rather than fail so the suite stays green.
    """
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    try:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("select 1")
    except psycopg.Error as exc:
        # Covers unreachable hosts and malformed DSNs (e.g. a Supabase HTTPS
        # URL mistakenly used as DATABASE_URL).
        pytest.skip(f"DB not usable: {exc}")


def test_ownership_key_lowercases_strips_punct_collapses_ws():
    assert ownership_key("  The   Witcher 3: Wild-Hunt!! ") == "the witcher 3 wild hunt"
    assert ownership_key("HALF-LIFE 2") == "half life 2"
    assert ownership_key(None) == ""
    assert ownership_key("") == ""


def test_vector_literal_format():
    assert _to_vector_literal([1.0, 2.5, -3.0]).startswith("[")
    assert _to_vector_literal([1.0, 2.5, -3.0]).endswith("]")
    assert _to_vector_literal([]) == "[]"


@pytest.mark.asyncio
async def test_vector_store_top_k_requires_db(candidates):
    await _require_db()
    from api.services.vector_store import VectorStore

    store = VectorStore()
    results = await store.top_k([0.0] * EMBEDDING_DIM, k=5)
    assert len(results) <= 5
    for r in results:
        assert r.similarity is None or 0.0 <= r.similarity <= 1.0


@pytest.mark.asyncio
async def test_dedup_filter_owned_requires_db(candidates):
    await _require_db()
    dedup = DeduplicationService()
    kept = await dedup.filter_owned(DEV_USER, candidates)
    assert len(kept) <= len(candidates)
