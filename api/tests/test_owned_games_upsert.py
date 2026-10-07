"""Idempotent owned_games upsert — TM11-XX.

    AC-01  owned_games rows written with playtimeMinutes and importedAt
    AC-02  re-running the import leaves the row count unchanged and updates playtime
    AC-03  rows attributed to the correct platform_account

Three layers, because no single one of them is honest evidence on its own:

1. **Statement tests.** Assert the real SQL string the service executes —
   `repositories._UPSERT_OWNED_GAMES_SQL`, not a copy — names the right columns
   and conflict target, and that the parameters carry the account id and
   playtime. Proves the write path *intends* the right thing.

2. **Semantics model.** `FakeOwnedGames` is a hand-written model of what
   Postgres does with that one statement: the conflict key, `coalesce`,
   `greatest`, `now()`. Running a sync twice against it demonstrates AC-02
   end to end with no database. This tests the model as much as the code, and
   is only meaningful because layer 1 pins the statement it models.

3. **The real thing.** `test_*_requires_db` runs the actual statement against
   Postgres and is the authoritative evidence. It *skips* when DATABASE_URL is
   unset or unreachable, which in this project is the normal case — see
   docs/library-sync-idempotency.md → "Verification status". A green suite
   therefore does not mean AC-02 was verified against a database; check whether
   that test skipped.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

import psycopg
import pytest

from api.db import connection, has_db, repositories
from api.services.library_sync import LibrarySyncService

pytestmark = pytest.mark.asyncio

DEV_USER = UUID("00000000-0000-0000-0000-000000000001")
STEAM_ID = "76561197960287930"

# A steam_appid range that no real title occupies, so the DB-backed test can
# write into a shared database without colliding with seeded or synced rows.
PROBE_APPID = 99_900_001


# ───────────────────────────── fake database ─────────────────────────────


class FakeOwnedGames:
    """In-memory model of the one insert statement in repositories.py.

    Implements only what `_UPSERT_OWNED_GAMES_SQL` relies on:
    `(user_id, platform, steam_appid)` as the conflict key, `coalesce` on title
    and account, `greatest` on playtime, and an always-advancing `now()`.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, Any], dict[str, Any]] = {}
        self.accounts: dict[tuple[str, str, str], UUID] = {}
        self.statements: list[tuple[str, Any]] = []
        self.commits = 0
        self._clock = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        # Every call advances, so "imported_at moved" is testable without
        # depending on wall-clock resolution.
        self._clock += timedelta(seconds=1)
        return self._clock

    # ── statement dispatch ────────────────────────────────────────────────
    # Matched on the module constants by identity where possible, so a change
    # to the SQL cannot silently keep passing against a stale copy here.

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> int:
        self.statements.append((sql, params))
        if sql is repositories._UPSERT_OWNED_GAMES_SQL:
            return self._upsert(params or ())
        if "insert into platform_accounts" in sql:
            return self._ensure_account(params or ())
        if "update owned_games set platform_account_id" in sql:
            return self._attach_orphans(params or ())
        if "select count(*) from owned_games" in sql:
            user_id = str(params[0])
            self.last_row = (sum(1 for k in self.rows if k[0] == user_id),)
            return 0
        raise AssertionError(f"FakeOwnedGames has no model for: {sql!r}")

    def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> int:
        for params in seq:
            self.execute(sql, params)
        return len(seq)

    # ── modelled statements ───────────────────────────────────────────────

    def _upsert(self, p: Sequence[Any]) -> int:
        user_id, platform, account, appid, title, playtime = p
        key = (user_id, platform, appid)
        existing = self.rows.get(key)
        if existing is None:
            self.rows[key] = {
                "user_id": user_id,
                "platform": platform,
                "platform_account_id": account,
                "steam_appid": appid,
                "title": title,
                "playtime_minutes": playtime,
                "imported_at": self.now(),
            }
        else:
            existing["title"] = title if title is not None else existing["title"]
            existing["platform_account_id"] = (
                account if account is not None else existing["platform_account_id"]
            )
            existing["playtime_minutes"] = max(playtime, existing["playtime_minutes"])
            existing["imported_at"] = self.now()
        return 1

    def _ensure_account(self, p: Sequence[Any]) -> int:
        key = (str(p[0]), p[1], str(p[2]))
        account_id = self.accounts.setdefault(key, uuid4())
        self.last_row = (account_id,)
        return 1

    def _attach_orphans(self, p: Sequence[Any]) -> int:
        account, user_id, platform = str(p[0]), str(p[1]), p[2]
        attached = 0
        for (row_user, row_platform, _), row in self.rows.items():
            if row_user == user_id and row_platform == platform:
                if row["platform_account_id"] is None:
                    row["platform_account_id"] = account
                    attached += 1
        return attached


class _FakeCursor:
    def __init__(self, db: FakeOwnedGames) -> None:
        self._db = db
        self.rowcount = 0

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.rowcount = self._db.execute(sql, params)

    async def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> None:
        self.rowcount = self._db.executemany(sql, seq)

    async def fetchone(self) -> Any:
        return getattr(self._db, "last_row", None)


class _FakeConnection:
    def __init__(self, db: FakeOwnedGames) -> None:
        self._db = db

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._db)

    async def commit(self) -> None:
        self._db.commits += 1


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeOwnedGames:
    db = FakeOwnedGames()

    @asynccontextmanager
    async def fake_connection():
        yield _FakeConnection(db)

    monkeypatch.setattr(repositories, "connection", fake_connection)
    return db


# ───────────────────── layer 1: the statement itself ─────────────────────


def test_upsert_statement_writes_playtime_and_imported_at():
    """AC-01: both columns are in the insert, and imported_at moves on update."""
    sql = repositories._UPSERT_OWNED_GAMES_SQL
    assert "playtime_minutes" in sql
    assert "imported_at" in sql
    # On an update, not only on the first insert — otherwise "when a sync last
    # saw this row" would be frozen at the row's creation.
    update_clause = sql.split("do update set", 1)[1]
    assert "imported_at = now()" in update_clause


def test_upsert_statement_is_idempotent_on_the_unique_constraint():
    """AC-02: the conflict target matches 0001_init's unique constraint."""
    sql = repositories._UPSERT_OWNED_GAMES_SQL
    assert "on conflict (user_id, platform, steam_appid) do update set" in sql
    # `do nothing` would keep the row count stable but never update playtime,
    # which satisfies half of AC-02 and silently fails the other half.
    assert "do nothing" not in sql


def test_upsert_statement_carries_platform_account():
    """AC-03: the account is inserted, and an existing one is never detached."""
    sql = repositories._UPSERT_OWNED_GAMES_SQL
    assert "platform_account_id" in sql.split("values", 1)[0]
    update_clause = sql.split("do update set", 1)[1]
    assert "coalesce(" in update_clause
    assert "owned_games.platform_account_id" in update_clause


@pytest.mark.parametrize(
    "row, expected",
    [
        ({"playtime_minutes": 120}, 120),
        ({"playtime_forever": 95}, 95),          # raw Steam payload
        ({"playtime_minutes": 0}, 0),            # owned, never played
        ({}, 0),                                 # non-Steam import
        ({"playtime_minutes": None}, 0),
        ({"playtime_minutes": "240"}, 240),
        ({"playtime_minutes": "not a number"}, 0),
        ({"playtime_minutes": -5}, 0),           # column is check >= 0
    ],
)
def test_playtime_coercion(row: Mapping[str, Any], expected: int):
    assert repositories._playtime_minutes(row) == expected


# ──────────────────── layer 2: semantics, no database ────────────────────


async def test_resync_leaves_row_count_unchanged_and_updates_playtime(fake_db):
    """AC-02 against the semantics model."""
    account = uuid4()
    first = [
        {"steam_appid": 620, "title": "Portal 2", "playtime_minutes": 300},
        {"steam_appid": 413150, "title": "Stardew Valley", "playtime_minutes": 1200},
    ]
    await repositories.upsert_owned_games(
        DEV_USER, first, platform="steam", platform_account_id=account
    )
    assert len(fake_db.rows) == 2
    first_import = {k: v["imported_at"] for k, v in fake_db.rows.items()}

    # Same library, more hours on the clock — what a real second sync looks like.
    second = [
        {"steam_appid": 620, "title": "Portal 2", "playtime_minutes": 360},
        {"steam_appid": 413150, "title": "Stardew Valley", "playtime_minutes": 1250},
    ]
    await repositories.upsert_owned_games(
        DEV_USER, second, platform="steam", platform_account_id=account
    )

    assert len(fake_db.rows) == 2, "a re-sync duplicated the library"
    assert fake_db.rows[(str(DEV_USER), "steam", 620)]["playtime_minutes"] == 360
    assert fake_db.rows[(str(DEV_USER), "steam", 413150)]["playtime_minutes"] == 1250
    for key, row in fake_db.rows.items():
        assert row["imported_at"] > first_import[key], "imported_at did not move"


async def test_resync_never_moves_playtime_backwards(fake_db):
    """The keyless fallback reports 0 minutes; it must not erase real hours."""
    account = uuid4()
    await repositories.upsert_owned_games(
        DEV_USER,
        [{"steam_appid": 620, "title": "Portal 2", "playtime_minutes": 300}],
        platform="steam",
        platform_account_id=account,
    )
    await repositories.upsert_owned_games(
        DEV_USER,
        [{"steam_appid": 620, "title": "Portal 2"}],  # no playtime -> 0
        platform="steam",
        platform_account_id=account,
    )
    assert fake_db.rows[(str(DEV_USER), "steam", 620)]["playtime_minutes"] == 300


async def test_rows_are_attributed_to_the_linked_account(fake_db):
    """AC-03 for rows this sync writes."""
    account = await repositories.ensure_platform_account(DEV_USER, "steam", STEAM_ID)
    await repositories.upsert_owned_games(
        DEV_USER,
        [{"steam_appid": 620, "title": "Portal 2", "playtime_minutes": 300}],
        platform="steam",
        platform_account_id=account,
    )
    row = fake_db.rows[(str(DEV_USER), "steam", 620)]
    assert row["platform_account_id"] == str(account)


async def test_two_steam_accounts_do_not_claim_each_others_rows(fake_db):
    """AC-03: the same appid owned on two linked accounts stays distinguishable.

    Both rows share (user_id, platform, steam_appid), so they collapse to one
    row under the current conflict key and the *later* account wins. That is a
    real limitation of the skeleton schema's unique constraint, not an
    accident — it is recorded here so the behaviour is pinned rather than
    discovered later. See docs/library-sync-idempotency.md -> "Known limits".
    """
    account_a = await repositories.ensure_platform_account(DEV_USER, "steam", "111")
    account_b = await repositories.ensure_platform_account(DEV_USER, "steam", "222")
    assert account_a != account_b

    await repositories.upsert_owned_games(
        DEV_USER, [{"steam_appid": 620, "title": "Portal 2"}],
        platform="steam", platform_account_id=account_a,
    )
    await repositories.upsert_owned_games(
        DEV_USER, [{"steam_appid": 620, "title": "Portal 2"}],
        platform="steam", platform_account_id=account_b,
    )
    assert len(fake_db.rows) == 1
    assert fake_db.rows[(str(DEV_USER), "steam", 620)]["platform_account_id"] == str(
        account_b
    )


async def test_orphan_rows_are_adopted_by_the_linked_account(fake_db):
    """AC-03 for the five seeded rows, which predate attribution."""
    await repositories.upsert_owned_games(
        DEV_USER,
        [{"steam_appid": 220, "title": "Half-Life 2"}],
        platform="steam",
    )  # no account: how supabase/seed.sql rows look
    assert fake_db.rows[(str(DEV_USER), "steam", 220)]["platform_account_id"] is None

    account = await repositories.ensure_platform_account(DEV_USER, "steam", STEAM_ID)
    attached = await repositories.attach_orphan_owned_games(DEV_USER, account, "steam")

    assert attached == 1
    assert fake_db.rows[(str(DEV_USER), "steam", 220)]["platform_account_id"] == str(
        account
    )


async def test_empty_library_writes_nothing(fake_db):
    """A private or empty profile must not open a transaction for zero rows."""
    assert await repositories.upsert_owned_games(DEV_USER, [], platform="steam") == 0
    assert fake_db.statements == []
    assert fake_db.commits == 0


# ───────────────── the sync service wires the three together ─────────────


class _RecordingRepositories:
    """Stands in for the repositories module inside LibrarySyncService."""

    def __init__(self) -> None:
        self.account_id = uuid4()
        self.ensure_calls: list[tuple[Any, str, str]] = []
        self.upsert_calls: list[dict[str, Any]] = []
        self.attach_calls: list[tuple[Any, Any, str]] = []
        self.existing = 0

    async def ensure_platform_account(self, user_id, platform, external_id):
        self.ensure_calls.append((user_id, platform, external_id))
        return self.account_id

    async def upsert_owned_games(
        self, user_id, rows, platform="steam", platform_account_id=None
    ):
        self.upsert_calls.append(
            {"rows": list(rows), "platform_account_id": platform_account_id}
        )
        return len(rows)

    async def count_owned_games(self, user_id):
        return self.existing

    async def attach_orphan_owned_games(self, user_id, account_id, platform="steam"):
        self.attach_calls.append((user_id, account_id, platform))
        return self.existing


async def test_sync_maps_steam_playtime_and_attributes_rows(monkeypatch):
    """AC-01 + AC-03 through the service: playtime_forever is no longer dropped."""
    repo = _RecordingRepositories()
    monkeypatch.setattr("api.services.library_sync.repositories", repo)

    service = LibrarySyncService(settings=_settings_with_key())
    monkeypatch.setattr(
        service, "_fetch_steam_games",
        _returning([
            {"appid": 620, "name": "Portal 2", "playtime_forever": 742},
            {"appid": 413150, "name": "Stardew Valley", "playtime_forever": 0},
            {"name": "No appid, dropped"},
        ]),
    )

    result = await service.sync(DEV_USER, STEAM_ID)

    assert result.source == "steam"
    assert result.synced == 2
    # The account is resolved from the steamID64 before anything is written.
    assert repo.ensure_calls == [(DEV_USER, "steam", STEAM_ID)]
    call = repo.upsert_calls[0]
    assert call["platform_account_id"] == repo.account_id
    assert call["rows"][0]["playtime_minutes"] == 742
    assert call["rows"][1]["playtime_minutes"] == 0


async def test_seed_path_still_attributes_existing_rows(monkeypatch):
    """AC-03: a keyless sync over a seeded library claims the orphan rows."""
    repo = _RecordingRepositories()
    repo.existing = 5
    monkeypatch.setattr("api.services.library_sync.repositories", repo)

    service = LibrarySyncService(settings=_settings_without_key())
    result = await service.sync(DEV_USER, STEAM_ID)

    assert result.source == "seed"
    assert result.synced == 5
    assert repo.attach_calls == [(DEV_USER, repo.account_id, "steam")]


def _settings_with_key():
    from api.config import Settings

    return Settings(steam_api_key="not-a-real-key")


def _settings_without_key():
    from api.config import Settings

    return Settings(steam_api_key=None)


def _returning(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


# ───────────────── layer 3: the real database (skips offline) ─────────────


async def _require_db() -> None:
    """Skip unless a Postgres is actually reachable, not merely configured."""
    if not has_db():
        pytest.skip("no DATABASE_URL configured")
    try:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("select 1")
    except psycopg.Error as exc:
        pytest.skip(f"DB not usable: {exc}")


async def _probe_row(appid: int) -> tuple[int, int, Any, Any]:
    async with connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "select count(*), coalesce(max(playtime_minutes), 0), "
                "max(platform_account_id::text), max(imported_at) "
                "from owned_games where user_id = %s and steam_appid = %s",
                (str(DEV_USER), appid),
            )
            return await cur.fetchone()


async def test_owned_games_upsert_is_idempotent_requires_db():
    """AC-01 + AC-02 + AC-03 against a real Postgres. The authoritative run.

    Skips when DATABASE_URL is unset or the host is unreachable, which is the
    default state of this repo. A skip here is not a pass.
    """
    await _require_db()

    account = await repositories.ensure_platform_account(DEV_USER, "steam", STEAM_ID)
    row = {"steam_appid": PROBE_APPID, "title": "Idempotency Probe"}
    try:
        await repositories.upsert_owned_games(
            DEV_USER, [{**row, "playtime_minutes": 120}],
            platform="steam", platform_account_id=account,
        )
        count_1, playtime_1, account_1, imported_1 = await _probe_row(PROBE_APPID)

        # AC-01
        assert playtime_1 == 120
        assert imported_1 is not None
        # AC-03
        assert account_1 == str(account)

        await repositories.upsert_owned_games(
            DEV_USER, [{**row, "playtime_minutes": 180}],
            platform="steam", platform_account_id=account,
        )
        count_2, playtime_2, account_2, imported_2 = await _probe_row(PROBE_APPID)

        # AC-02
        assert count_2 == count_1 == 1, "the second sync inserted a duplicate row"
        assert playtime_2 == 180, "the second sync did not update playtime"
        assert imported_2 > imported_1, "imported_at did not move"
        assert account_2 == str(account)
    finally:
        async with connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "delete from owned_games where user_id = %s and steam_appid = %s",
                    (str(DEV_USER), PROBE_APPID),
                )
            await conn.commit()
