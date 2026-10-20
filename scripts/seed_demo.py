"""Seed a reproducible demo account for CI, local dev and the demo (TM11-88).

One command takes an empty Postgres (pgvector) to a database the API can serve:

  1. schema     the local 0001_init.sql slice and the migrations that patch it
  2. catalogue  the committed 167-game fixture, via scripts/seed_games.py
  3. account    the dev user with a linked Steam account, a library, past
                queries with ranked recommendations, and thumbs up/down feedback

The account is the one in DEV_USER_ID, because that is the user every API route
acts as until real auth lands. Every row has a fixed key, so a rerun updates
rows in place and never adds a second copy. Nothing here needs an API key, the
network or torch.

Usage (from the repo root, with the venv active and DATABASE_URL set):
    python scripts/seed_demo.py             # schema + catalogue + demo account
    python scripts/seed_demo.py --reset     # wipe the demo account first, then seed
    python scripts/seed_demo.py --check     # seed nothing; exit 1 if anything is missing

Exits 0 on success, 1 when --check finds missing rows, and 2 when there is no
database or it has the hosted Supabase schema instead of the local slice.

Live recommendations also need vectors: run scripts/embed_games.py after this.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

from api.config import get_settings  # noqa: E402
from api.db import connection, has_db  # noqa: E402
from seed_games import load_fixture, upsert_games  # noqa: E402

MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"

# The migrations that build the schema api/db/repositories.py reads and writes.
# The other files in supabase/migrations build the hosted Supabase shape (they
# need the auth schema) and do not apply here. See docs/steam-library.md, Known gap.
LOCAL_MIGRATIONS = (
    "0001_init.sql",
    "0002_embedding_dim_384.sql",
    "20261006120000_owned_games_playtime.sql",
    "20261012120000_owned_games_unique_manual_game.sql",
    "20261012130000_owned_games_import_method.sql",
)

# Every migration above is safe to rerun except 0002, which clears every vector
# on its way to vector(384). Skip it once the column already has that size, so a
# rerun keeps the embeddings embed_games.py made.
_ALREADY_APPLIED_PROBES = {
    "0002_embedding_dim_384.sql": (
        "select format_type(atttypid, atttypmod) = 'vector(384)' "
        "from pg_attribute "
        "where attrelid = to_regclass('public.games') and attname = 'embedding'"
    ),
}

# uuid5 keys: the same text always gives the same id, so reruns hit the same rows.
DEMO_NAMESPACE = uuid5(NAMESPACE_URL, "https://gamegpt.local/demo-seed")

# The email 0001_init.sql gives the default dev user. Users is unique on email,
# so any other DEV_USER_ID gets its own address (see demo_email).
DEMO_EMAIL = "dev@gamegpt.local"
DEFAULT_DEV_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
# A made-up steamID64. Library sync with no STEAM_API_KEY never calls Steam with it.
DEMO_STEAM_ID = "76561198000000088"


@dataclass(frozen=True)
class OwnedTitle:
    steam_appid: int
    title: str
    playtime_minutes: int


@dataclass(frozen=True)
class DemoRecommendation:
    steam_appid: int
    title: str
    reason: str


@dataclass(frozen=True)
class DemoQuery:
    text: str
    recommendations: tuple[DemoRecommendation, ...]
    # (rank, vote) pairs, vote 'up' or 'down'
    votes: tuple[tuple[int, str], ...]

    @property
    def query_id(self) -> UUID:
        return uuid5(DEMO_NAMESPACE, f"query:{self.text}")

    def feedback_id(self, rank: int) -> UUID:
        return uuid5(DEMO_NAMESPACE, f"feedback:{self.text}:{rank}")


# The first five match supabase/seed.sql, so dedup drops the same titles either way.
DEMO_LIBRARY = (
    OwnedTitle(413150, "Stardew Valley", 5400),
    OwnedTitle(646570, "Slay the Spire", 4500),
    OwnedTitle(1145360, "Hades", 3120),
    OwnedTitle(367520, "Hollow Knight", 2280),
    OwnedTitle(220, "Half-Life 2", 1260),
    OwnedTitle(504230, "Celeste", 960),
    OwnedTitle(620, "Portal 2", 840),
)

DEMO_QUERIES = (
    DemoQuery(
        text="something cozy and relaxing to play after work",
        recommendations=(
            DemoRecommendation(1055540, "A Short Hike",
                               "A gentle island climb you can finish in an evening."),
            DemoRecommendation(914800, "Coffee Talk",
                               "Brew drinks and listen to stories, no fail states."),
            DemoRecommendation(1135690, "Unpacking",
                               "Calm, tidy puzzles that tell a story through objects."),
        ),
        votes=((1, "up"), (3, "up")),
    ),
    DemoQuery(
        text="a hard roguelike like the ones I already love",
        recommendations=(
            DemoRecommendation(2379780, "Balatro",
                               "Deckbuilding runs with the same one-more-go pull as your "
                               "favourite card roguelike."),
            DemoRecommendation(588650, "Dead Cells",
                               "Fast, punishing runs with tight melee combat."),
            DemoRecommendation(311690, "Enter the Gungeon",
                               "Bullet-hell rooms and a deep pool of unlocks."),
        ),
        votes=((1, "up"), (2, "down")),
    ),
    DemoQuery(
        text="story-rich puzzle game with a mystery to solve",
        recommendations=(
            DemoRecommendation(653530, "Return of the Obra Dinn",
                               "Deduce the fate of a whole crew from frozen moments."),
            DemoRecommendation(753640, "Outer Wilds",
                               "A solar system that is one big mystery to unravel."),
            DemoRecommendation(736260, "Baba Is You",
                               "Rewrite the rules themselves to solve each level."),
        ),
        votes=((2, "up"),),
    ),
)


@dataclass(frozen=True)
class SeedSummary:
    platform_accounts: int
    owned_games: int
    owned_games_linked: int
    queries: int
    recommendations: int
    feedback: int


EXPECTED = SeedSummary(
    platform_accounts=1,
    owned_games=len(DEMO_LIBRARY),
    owned_games_linked=len(DEMO_LIBRARY),
    queries=len(DEMO_QUERIES),
    recommendations=sum(len(q.recommendations) for q in DEMO_QUERIES),
    feedback=sum(len(q.votes) for q in DEMO_QUERIES),
)


def demo_email(user_id: UUID) -> str:
    if user_id == DEFAULT_DEV_USER_ID:
        return DEMO_EMAIL
    return f"demo-{user_id}@gamegpt.local"


def demo_appids() -> set[int]:
    """Every steam_appid the demo account points at."""
    appids = {t.steam_appid for t in DEMO_LIBRARY}
    for q in DEMO_QUERIES:
        appids.update(r.steam_appid for r in q.recommendations)
    return appids


# ─────────────────────────── schema ───────────────────────────


async def is_hosted_schema(cur: Any) -> bool:
    """True for the hosted Supabase shape, where users is keyed on user_id."""
    await cur.execute(
        "select exists (select 1 from information_schema.columns "
        "where table_schema = 'public' and table_name = 'users' and column_name = 'user_id')"
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def apply_migrations(cur: Any) -> list[str]:
    """Apply LOCAL_MIGRATIONS in order. Returns the names that ran."""
    applied: list[str] = []
    for name in LOCAL_MIGRATIONS:
        probe = _ALREADY_APPLIED_PROBES.get(name)
        if probe is not None:
            await cur.execute(probe)
            row = await cur.fetchone()
            if row and row[0]:
                continue
        # No parameters, so psycopg sends the file as one simple query and the
        # multi-statement script (do $$ blocks included) runs as written.
        await cur.execute((MIGRATIONS_DIR / name).read_text(encoding="utf-8"))
        applied.append(name)
    return applied


# ─────────────────────────── demo account ───────────────────────────


async def _game_ids_by_appid(cur: Any, appids: set[int]) -> dict[int, UUID]:
    await cur.execute(
        "select steam_appid, id from games where steam_appid = any(%s)", (sorted(appids),)
    )
    return {appid: game_id for appid, game_id in await cur.fetchall()}


async def reset_demo_account(cur: Any, user_id: UUID) -> None:
    """Delete the account's rows. recommendations and feedback cascade from queries."""
    for table in ("queries", "owned_games", "platform_accounts"):
        await cur.execute(f"delete from {table} where user_id = %s", (str(user_id),))


async def seed_demo_account(cur: Any, user_id: UUID) -> None:
    """Write the demo account. Each statement upserts on a fixed key."""
    game_ids = await _game_ids_by_appid(cur, demo_appids())
    uid = str(user_id)

    await cur.execute(
        "insert into users (id, email) values (%s, %s) on conflict (id) do nothing",
        (uid, demo_email(user_id)),
    )
    await cur.execute(
        "insert into platform_accounts (user_id, platform, external_id) "
        "values (%s, 'steam', %s) "
        "on conflict (user_id, platform, external_id) do nothing",
        (uid, DEMO_STEAM_ID),
    )
    await cur.executemany(
        "insert into owned_games "
        "(user_id, platform, steam_appid, title, playtime_minutes, game_id) "
        "values (%s, 'steam', %s, %s, %s, %s) "
        "on conflict (user_id, platform, steam_appid) do update set "
        "title = excluded.title, game_id = excluded.game_id, "
        # Unlike a Steam sync, the seed is the source of truth: reset playtime to it.
        "playtime_minutes = excluded.playtime_minutes",
        [
            (uid, t.steam_appid, t.title, t.playtime_minutes, _str_or_none(game_ids, t))
            for t in DEMO_LIBRARY
        ],
    )
    for q in DEMO_QUERIES:
        await cur.execute(
            "insert into queries (id, user_id, text) values (%s, %s, %s) "
            "on conflict (id) do nothing",
            (str(q.query_id), uid, q.text),
        )
        await cur.executemany(
            "insert into recommendations (query_id, game_id, rank, title, reason) "
            "values (%s, %s, %s, %s, %s) "
            "on conflict (query_id, rank) do update set "
            "game_id = excluded.game_id, title = excluded.title, reason = excluded.reason",
            [
                (str(q.query_id), _str_or_none(game_ids, r), rank, r.title, r.reason)
                for rank, r in enumerate(q.recommendations, start=1)
            ],
        )
        await cur.executemany(
            "insert into recommendation_feedback (id, query_id, game_id, title, rank, vote) "
            "values (%s, %s, %s, %s, %s, %s) "
            "on conflict (id) do update set vote = excluded.vote",
            [
                (
                    str(q.feedback_id(rank)), str(q.query_id),
                    _str_or_none(game_ids, q.recommendations[rank - 1]),
                    q.recommendations[rank - 1].title, rank, vote,
                )
                for rank, vote in q.votes
            ],
        )


def _str_or_none(game_ids: dict[int, UUID], item: OwnedTitle | DemoRecommendation) -> str | None:
    game_id = game_ids.get(item.steam_appid)
    return str(game_id) if game_id is not None else None


async def summarise_demo_account(cur: Any, user_id: UUID) -> SeedSummary:
    """Count what the account has now, in the same shape as EXPECTED."""
    await cur.execute(
        "select "
        "(select count(*) from platform_accounts where user_id = %(u)s), "
        "(select count(*) from owned_games where user_id = %(u)s), "
        "(select count(*) from owned_games where user_id = %(u)s and game_id is not null), "
        "(select count(*) from queries where user_id = %(u)s), "
        "(select count(*) from recommendations r join queries q on q.id = r.query_id "
        " where q.user_id = %(u)s), "
        "(select count(*) from recommendation_feedback f join queries q on q.id = f.query_id "
        " where q.user_id = %(u)s)",
        {"u": str(user_id)},
    )
    return SeedSummary(*await cur.fetchone())


def missing_rows(actual: SeedSummary, expected: SeedSummary = EXPECTED) -> list[str]:
    """Human-readable lines for every count below what the seed writes."""
    return [
        f"{field}: {getattr(actual, field)} of {getattr(expected, field)}"
        for field in expected.__dataclass_fields__
        if getattr(actual, field) < getattr(expected, field)
    ]


# ─────────────────────────── main ───────────────────────────


async def run(args: argparse.Namespace) -> int:
    user_id = UUID(get_settings().dev_user_id)

    async with connection() as conn:
        async with conn.cursor() as cur:
            if await is_hosted_schema(cur):
                print("seed_demo: this database has the hosted Supabase schema. The demo "
                      "seed targets the local 0001_init.sql slice; see docs/RUNBOOK.md.")
                return 2

            if not args.check:
                applied = await apply_migrations(cur)
                await conn.commit()
                skipped = len(LOCAL_MIGRATIONS) - len(applied)
                print(f"seed_demo: schema ready (ran {len(applied)} local migration(s), "
                      f"{skipped} already in place).")

    if not args.check:
        inserted, updated, _ = await upsert_games(load_fixture())
        print(f"seed_demo: catalogue ready (inserted={inserted} updated={updated}).")

    async with connection() as conn:
        async with conn.cursor() as cur:
            if not args.check:
                if args.reset:
                    await reset_demo_account(cur, user_id)
                await seed_demo_account(cur, user_id)
                await conn.commit()
            summary = await summarise_demo_account(cur, user_id)

    print(f"seed_demo: account {user_id} ({demo_email(user_id)}): {summary}")
    missing = missing_rows(summary)
    if missing:
        print("seed_demo: demo account is incomplete: " + "; ".join(missing))
        return 1
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the reproducible demo account.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--reset", action="store_true",
                      help="delete the demo account's rows before seeding")
    mode.add_argument("--check", action="store_true",
                      help="write nothing; exit 1 unless the demo account is complete")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not has_db():
        print("seed_demo: DATABASE_URL is not set, so there is no database to seed.")
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
