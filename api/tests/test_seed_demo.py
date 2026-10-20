"""scripts/seed_demo.py: the reproducible demo account (TM11-88).

The data checks keep the seed consistent with the catalogue fixture and with
dedup. The run checks fake the database: a cursor that records every statement
and answers the few selects the script makes.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"


def load_script(name: str = "seed_demo"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules while the class is built
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


seed_demo = load_script()


class FakeCursor:
    def __init__(self, *, hosted: bool = False, vector_384: bool = False,
                 counts: tuple[int, ...] | None = None) -> None:
        self.statements: list[tuple[str, object]] = []
        self.hosted = hosted
        self.vector_384 = vector_384
        self.counts = counts or tuple(
            getattr(seed_demo.EXPECTED, f) for f in seed_demo.EXPECTED.__dataclass_fields__
        )
        self._last = ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self._last = sql

    async def executemany(self, sql, params_seq):
        self.statements.append((sql, list(params_seq)))
        self._last = sql

    async def fetchone(self):
        if "information_schema.columns" in self._last:
            return (self.hosted,)
        if "format_type" in self._last:
            return (self.vector_384,)
        return self.counts

    async def fetchall(self):
        # games lookup: every demo appid is in the catalogue
        return [(appid, uuid4()) for appid in sorted(seed_demo.demo_appids())]

    def ran(self, fragment: str) -> list[tuple[str, object]]:
        return [s for s in self.statements if fragment in s[0]]


class FakeConnection:
    def __init__(self, cur: FakeCursor) -> None:
        self.cur = cur
        self.commits = 0

    def cursor(self):
        return self.cur

    async def commit(self):
        self.commits += 1


@pytest.fixture
def fake_db(monkeypatch):
    cur = FakeCursor()
    conn = FakeConnection(cur)
    catalogue_upserts: list[int] = []

    @asynccontextmanager
    async def connection():
        yield conn

    async def upsert_games(games):
        catalogue_upserts.append(len(games))
        return len(games), 0, 0

    monkeypatch.setattr(seed_demo, "connection", connection)
    monkeypatch.setattr(seed_demo, "has_db", lambda: True)
    monkeypatch.setattr(seed_demo, "upsert_games", upsert_games)
    conn.catalogue_upserts = catalogue_upserts
    return conn


def run(argv: list[str]) -> int:
    return seed_demo.main(argv)


# ─────────────────────────── the data itself ───────────────────────────


def test_every_seeded_game_is_in_the_catalogue_fixture():
    fixture_appids = {g["steam_appid"] for g in seed_demo.load_fixture()}
    assert seed_demo.demo_appids() <= fixture_appids


def test_seeded_titles_match_the_fixture_titles():
    titles = {g["steam_appid"]: g["title"] for g in seed_demo.load_fixture()}
    for owned in seed_demo.DEMO_LIBRARY:
        assert owned.title == titles[owned.steam_appid]
    for q in seed_demo.DEMO_QUERIES:
        for r in q.recommendations:
            assert r.title == titles[r.steam_appid]


def test_no_seeded_recommendation_is_a_game_the_user_owns():
    owned = {t.steam_appid for t in seed_demo.DEMO_LIBRARY}
    for q in seed_demo.DEMO_QUERIES:
        assert not owned & {r.steam_appid for r in q.recommendations}, q.text


def test_each_query_has_three_to_five_recommendations():
    for q in seed_demo.DEMO_QUERIES:
        assert 3 <= len(q.recommendations) <= 5


def test_every_vote_points_at_a_real_rank_and_is_up_or_down():
    for q in seed_demo.DEMO_QUERIES:
        ranks = [rank for rank, _ in q.votes]
        assert len(ranks) == len(set(ranks))
        for rank, vote in q.votes:
            assert 1 <= rank <= len(q.recommendations)
            assert vote in ("up", "down")


def test_ids_are_the_same_on_every_run_and_never_collide():
    reloaded = load_script("seed_demo_reloaded")
    ids = [q.query_id for q in seed_demo.DEMO_QUERIES]
    assert ids == [q.query_id for q in reloaded.DEMO_QUERIES]
    feedback_ids = [q.feedback_id(rank) for q in seed_demo.DEMO_QUERIES for rank, _ in q.votes]
    assert len(set(ids + feedback_ids)) == len(ids) + len(feedback_ids)


def test_the_default_dev_user_keeps_the_0001_init_email():
    assert seed_demo.demo_email(seed_demo.DEFAULT_DEV_USER_ID) == "dev@gamegpt.local"
    other = UUID("00000000-0000-0000-0000-000000000042")
    assert seed_demo.demo_email(other) != "dev@gamegpt.local"


def test_every_local_migration_file_exists():
    for name in seed_demo.LOCAL_MIGRATIONS:
        assert (seed_demo.MIGRATIONS_DIR / name).is_file(), name


# ─────────────────────────── running it ───────────────────────────


def test_no_database_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(seed_demo, "has_db", lambda: False)
    assert run([]) == 2
    assert "DATABASE_URL is not set" in capsys.readouterr().out


def test_a_full_seed_writes_every_part_of_the_account(fake_db):
    assert run([]) == 0

    cur = fake_db.cur
    assert fake_db.catalogue_upserts == [len(seed_demo.load_fixture())]
    assert cur.ran("insert into users")
    assert cur.ran("insert into platform_accounts")
    [(_, owned_rows)] = cur.ran("insert into owned_games")
    assert len(owned_rows) == len(seed_demo.DEMO_LIBRARY)
    assert all(row[-1] is not None for row in owned_rows)  # linked to a games row
    assert len(cur.ran("insert into queries")) == len(seed_demo.DEMO_QUERIES)
    assert len(cur.ran("insert into recommendations")) == len(seed_demo.DEMO_QUERIES)
    assert cur.ran("insert into recommendation_feedback")
    assert not cur.ran("delete from")


def test_every_write_is_an_upsert_so_a_rerun_adds_nothing(fake_db):
    run([])
    for sql, _ in fake_db.cur.statements:
        if sql.lstrip().startswith("insert into"):
            assert "on conflict" in sql, sql


def test_reset_deletes_the_account_before_seeding_it(fake_db):
    assert run(["--reset"]) == 0

    statements = [sql for sql, _ in fake_db.cur.statements]
    first_delete = next(i for i, s in enumerate(statements) if s.startswith("delete from"))
    first_user_insert = next(
        i for i, s in enumerate(statements) if s.startswith("insert into users")
    )
    assert first_delete < first_user_insert
    deleted = {s.split()[2] for s in statements if s.startswith("delete from")}
    assert deleted == {"queries", "owned_games", "platform_accounts"}


def test_check_writes_nothing_and_passes_on_a_complete_account(fake_db):
    assert run(["--check"]) == 0
    assert not [s for s, _ in fake_db.cur.statements if s.lstrip().startswith("insert")]
    assert fake_db.catalogue_upserts == []
    assert fake_db.commits == 0


def test_check_exits_1_and_names_what_is_missing(fake_db, capsys):
    fake_db.cur.counts = (1, 7, 7, 0, 0, 0)

    assert run(["--check"]) == 1
    out = capsys.readouterr().out
    assert "queries: 0 of 3" in out
    assert "owned_games" not in out.split("incomplete:")[1]


def test_the_hosted_supabase_schema_is_refused_untouched(fake_db, capsys):
    fake_db.cur.hosted = True

    assert run([]) == 2
    assert "hosted Supabase schema" in capsys.readouterr().out
    assert len(fake_db.cur.statements) == 1  # only the schema probe
    assert fake_db.catalogue_upserts == []


def test_0002_is_skipped_once_embeddings_are_384_dim_so_vectors_survive():
    cur = FakeCursor(vector_384=True)
    applied = asyncio.run(seed_demo.apply_migrations(cur))

    assert "0002_embedding_dim_384.sql" not in applied
    assert len(applied) == len(seed_demo.LOCAL_MIGRATIONS) - 1
    assert not cur.ran("update games set embedding = null")


def test_0002_runs_on_a_database_that_still_needs_it():
    cur = FakeCursor(vector_384=False)
    applied = asyncio.run(seed_demo.apply_migrations(cur))
    assert applied == list(seed_demo.LOCAL_MIGRATIONS)


def test_reset_and_check_cannot_be_combined():
    with pytest.raises(SystemExit):
        seed_demo._parse_args(["--reset", "--check"])


def test_the_script_runs_from_any_working_directory():
    # seed_demo imports seed_games as a sibling; loading it by path must work.
    assert "seed_games" in sys.modules
    assert isinstance(seed_demo._parse_args([]), argparse.Namespace)
