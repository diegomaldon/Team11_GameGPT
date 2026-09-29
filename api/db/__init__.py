"""Database layer.

`pool.py` is shared contract infra written in Phase 1 — the single place a
psycopg async connection is opened and where pgvector's type adapter is
registered. Agent C owns everything else here (repositories/persistence).
"""

from api.db.pool import connection, has_db

__all__ = ["connection", "has_db"]
