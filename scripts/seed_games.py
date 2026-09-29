"""Seed the `games` table.

Pulls ~150 games from the RAWG API (`settings.rawg_api_key`) when a key is
present. With no key — the default in this keyless dev environment — loads
the committed fixture at `scripts/fixtures/games.json` instead, so the
pipeline always has a real, varied catalog to run against.

Idempotent: every row is upserted `on conflict (steam_appid)`, so running
this script twice never duplicates a row — the second run reports the same
games as "updated" rather than inserting them again.

Usage (from repo root, with the venv active):
    python scripts/seed_games.py
    python scripts/seed_games.py --source fixture   # force the fixture even if a RAWG key is set
    python scripts/seed_games.py --limit 50          # seed fewer rows, useful for a quick smoke test
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.config import get_settings  # noqa: E402
from api.db import connection, has_db  # noqa: E402
from api.services.metadata_client import (  # noqa: E402
    MetadataClient,
    MetadataError,
    PermanentMetadataError,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "games.json"
RAWG_PAGE_SIZE = 40
DEFAULT_TARGET = 150

_STEAM_APPID_RE = re.compile(r"store\.steampowered\.com/app/(\d+)")


def load_fixture() -> list[dict[str, Any]]:
    """Load the committed offline fixture."""
    with FIXTURE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────── RAWG fetch ───────────────────────────
# Rate limiting, transient-retry with backoff, and permanent-skip all live in
# MetadataClient now; these helpers just shape the RAWG calls the seed needs.


async def _rawg_list_page(client: MetadataClient, page: int) -> list[dict[str, Any]]:
    return await client.list_games(limit=RAWG_PAGE_SIZE, page=page, ordering="-added")


async def _rawg_detail(client: MetadataClient, game_id: int) -> dict[str, Any]:
    return await client.fetch_game(game_id)


async def _rawg_steam_appid(client: MetadataClient, game_id: int) -> int | None:
    try:
        data = await client.fetch_stores(game_id)
    except PermanentMetadataError:
        # No store list for this title (e.g. 404) -> no discoverable Steam link.
        return None
    for entry in data.get("results", []):
        url = entry.get("url") or ""
        match = _STEAM_APPID_RE.search(url)
        if match:
            return int(match.group(1))
    return None


def _normalize_rawg_game(listing: dict[str, Any], detail: dict[str, Any], steam_appid: int | None) -> dict[str, Any]:
    genres = [g["name"] for g in listing.get("genres", []) if g.get("name")]
    tags = [t["name"] for t in (listing.get("tags") or [])[:8] if t.get("name")]
    developers = [d["name"] for d in detail.get("developers", []) if d.get("name")]
    rating = detail.get("rating") or listing.get("rating") or 0.0  # RAWG rating is 0..5
    review_score = round(min(max(rating / 5.0, 0.0), 1.0), 2) if rating else None
    description = (detail.get("description_raw") or "").strip()
    if len(description) > 600:
        description = description[:597].rstrip() + "..."
    return {
        "title": listing.get("name") or detail.get("name"),
        "description": description or None,
        "genres": genres,
        "tags": tags,
        "release_date": listing.get("released") or detail.get("released"),
        "developer": developers[0] if developers else None,
        "review_score": review_score,
        "steam_appid": steam_appid,
    }


async def fetch_rawg_games(target: int = DEFAULT_TARGET) -> list[dict[str, Any]]:
    """Pull `target` games from RAWG, enriched with description/developer/steam appid.

    Games RAWG has no discoverable Steam store link for are dropped (not just
    left with a null appid) so idempotency holds: the same games are skipped
    on every run instead of being inserted fresh each time with a random id.

    The RAWG key is read from settings by MetadataClient; the caller only needs
    to have confirmed one is set. A shared httpx client is injected so the whole
    pull reuses one connection pool while the client paces + retries every hop.
    """
    games: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0) as http:
        client = MetadataClient(http_client=http)
        page = 1
        listings: list[dict[str, Any]] = []
        while len(listings) < target and page <= 10:
            batch = await _rawg_list_page(client, page)
            if not batch:
                break
            listings.extend(batch)
            page += 1
        listings = listings[:target]

        sem = asyncio.Semaphore(5)

        async def _enrich(listing: dict[str, Any]) -> dict[str, Any] | None:
            game_id = listing.get("id")
            if game_id is None:
                return None
            async with sem:
                try:
                    detail, steam_appid = await asyncio.gather(
                        _rawg_detail(client, game_id),
                        _rawg_steam_appid(client, game_id),
                    )
                except MetadataError:
                    # Detail unavailable (permanent 4xx or exhausted retries) -> skip.
                    return None
            if steam_appid is None:
                return None
            return _normalize_rawg_game(listing, detail, steam_appid)

        results = await asyncio.gather(*(_enrich(listing) for listing in listings))
        games = [g for g in results if g]
    return games


# ─────────────────────────── upsert ───────────────────────────


async def upsert_games(games: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Upsert rows into `games`, keyed on `steam_appid`. Returns (inserted, updated, skipped)."""
    inserted = updated = skipped = 0
    async with connection() as conn:
        async with conn.cursor() as cur:
            for g in games:
                appid = g.get("steam_appid")
                if appid is None:
                    skipped += 1
                    continue
                await cur.execute(
                    """
                    insert into games
                        (title, description, genres, tags, release_date, developer, review_score, steam_appid)
                    values
                        (%s, %s, %s::text[], %s::text[], %s, %s, %s, %s)
                    on conflict (steam_appid) do update set
                        title = excluded.title,
                        description = excluded.description,
                        genres = excluded.genres,
                        tags = excluded.tags,
                        release_date = excluded.release_date,
                        developer = excluded.developer,
                        review_score = excluded.review_score
                    returning (xmax = 0) as was_insert
                    """,
                    (
                        g.get("title"),
                        g.get("description"),
                        g.get("genres") or [],
                        g.get("tags") or [],
                        g.get("release_date"),
                        g.get("developer"),
                        g.get("review_score"),
                        appid,
                    ),
                )
                row = await cur.fetchone()
                if row and row[0]:
                    inserted += 1
                else:
                    updated += 1
        await conn.commit()
    return inserted, updated, skipped


# ─────────────────────────── main ───────────────────────────


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the games table from RAWG or the offline fixture.")
    parser.add_argument("--source", choices=["auto", "rawg", "fixture"], default="auto",
                        help="Force a source instead of auto-detecting from RAWG_API_KEY.")
    parser.add_argument("--limit", type=int, default=DEFAULT_TARGET, help="How many games to seed.")
    args = parser.parse_args()

    if not has_db():
        print("seed_games: DATABASE_URL is not set - skipping (no DB to seed).")
        return 0

    settings = get_settings()
    use_rawg = args.source == "rawg" or (args.source == "auto" and bool(settings.rawg_api_key))

    games: list[dict[str, Any]]
    source_label: str
    if use_rawg:
        if not settings.rawg_api_key:
            print("seed_games: --source rawg requested but RAWG_API_KEY is unset. Aborting.")
            return 1
        print(f"seed_games: fetching up to {args.limit} games from RAWG...")
        try:
            games = await fetch_rawg_games(target=args.limit)
        except Exception as exc:  # network/API failure -> fall back rather than crash the seed
            print(f"seed_games: RAWG fetch failed ({exc!r}); falling back to the fixture.")
            games = load_fixture()[: args.limit]
            source_label = "fixture (RAWG fallback)"
        else:
            source_label = "rawg"
        if use_rawg and not games:
            print("seed_games: RAWG returned no usable games; falling back to the fixture.")
            games = load_fixture()[: args.limit]
            source_label = "fixture (RAWG fallback)"
    else:
        print("seed_games: no RAWG_API_KEY set - loading the offline fixture.")
        games = load_fixture()[: args.limit]
        source_label = "fixture"

    print(f"seed_games: seeding {len(games)} games (source: {source_label})...")
    inserted, updated, skipped = await upsert_games(games)
    print(
        f"seed_games: done. inserted={inserted} updated={updated} skipped={skipped} "
        f"(skipped rows had no steam_appid and were not written)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
