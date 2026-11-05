#!/usr/bin/env python3
"""Seed-catalogue row source for ingest_games.py, with no RAWG dependency (TM11-159).

RAWG is down, so the hosted catalogue is rebuilt from the committed fixture
`scripts/fixtures/games.json` (167 games, every TM11-63 benchmark title). That
file is in the local-schema shape that seed_games.py writes; this module maps
each entry to the prototype row shape that ingest_games.py validates and
upserts, keyed on `steam_appid`:

  python3 scripts/ingest_games.py --source-func catalogue_source:fetch_seed_catalogue \\
      --source steam-seed --target 167

Mapping, fixture -> hosted `games`:

  steam_appid        -> source "steam", source_id   (upsert key: steam_appid)
  developer          -> developers [developer]
  review_score 0..1  -> review_score 0..100 (smallint)
  steam_appid        -> available_platforms ["STEAM"],
                        purchase_links {"STEAM": store.steampowered.com/app/<id>}

Only Steam is claimed: every entry has a Steam app id, and the fixture has no
Xbox or Epic data, so none is invented. An entry with no steam_appid is passed
through without a source_id so the ingest job rejects it with a logged reason
rather than inserting a row nothing can key on.

The hosted load uses fetch_steam_enriched_catalogue, which adds what the
RAWG-era rows carry and the fixture lacks, from the cached Steam store details
(scripts/fixtures/steam_appdetails.json, filled by steam_store.py):

  metacritic score   -> critic_score          (when Steam has one)
  publishers         -> publishers
  developers         -> developers             (Steam's list; the fixture's if empty)
  header_image       -> header_image_url
  categories         -> appended to tags       ("Single-player", "Co-op", ...)

The fixture's description, genres, tags and review score are kept: the TM11-63
benchmark and the embedding text were built on them. An app with no cache entry,
or one Steam doesn't know, loads unenriched and is logged.

  python3 scripts/ingest_games.py --source-func catalogue_source:fetch_steam_enriched_catalogue \\
      --source steam-seed --target 167

Stdlib only.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Iterator

log = logging.getLogger("catalogue_source")

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "games.json"
STEAM_CACHE_PATH = Path(__file__).resolve().parent / "fixtures" / "steam_appdetails.json"
SOURCE = "steam"
STEAM_STORE_URL = "https://store.steampowered.com/app/{appid}"


def load_fixture(path: Path = FIXTURE_PATH) -> list[dict]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _review_score(value) -> int | float | None:
    """Fixture scores are 0..1 fractions; the hosted column is a 0..100 smallint.

    A value already above 1 is assumed to be on the 0..100 scale and left for
    validation to range-check. Non-numbers are passed through for the same reason.
    """
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(value * 100) if 0 <= value <= 1 else value


def to_ingest_row(entry: dict) -> dict:
    """Map one fixture entry to an ingest_games.py row."""
    appid = entry.get("steam_appid")
    has_appid = isinstance(appid, int) and not isinstance(appid, bool) and appid > 0
    developer = entry.get("developer")
    return {
        "source": SOURCE,
        "source_id": appid if has_appid else None,
        "title": entry.get("title"),
        "description": entry.get("description"),
        "genres": entry.get("genres") or [],
        "tags": entry.get("tags") or [],
        "available_platforms": ["STEAM"] if has_appid else [],
        "purchase_links": {"STEAM": STEAM_STORE_URL.format(appid=appid)} if has_appid else {},
        "critic_score": None,
        "review_score": _review_score(entry.get("review_score")),
        "release_date": entry.get("release_date"),
        "developers": [developer] if isinstance(developer, str) and developer.strip() else [],
        "publishers": [],
        "header_image_url": None,
    }


def rows_from(entries: Iterable[dict], limit: int | None = None) -> Iterator[dict]:
    for i, entry in enumerate(entries):
        if limit is not None and i >= limit:
            return
        yield to_ingest_row(entry)


def fetch_seed_catalogue(limit: int | None = None, path: Path = FIXTURE_PATH) -> Iterator[dict]:
    """--source-func entry point: ingest_games.py calls it as fetch_seed_catalogue(limit=N)."""
    return rows_from(load_fixture(path), limit)


def enrich(row: dict, details: dict | None) -> dict:
    """Merge one cached Steam store entry (steam_store.trim shape) into an ingest row."""
    if not details or not details.get("success"):
        return row
    tags = list(row.get("tags") or [])
    seen = {t.casefold() for t in tags}
    for c in details.get("categories") or []:
        if c.casefold() not in seen:
            tags.append(c)
            seen.add(c.casefold())
    return {
        **row,
        "tags": tags,
        "critic_score": details.get("metacritic"),
        "publishers": details.get("publishers") or row.get("publishers") or [],
        "developers": details.get("developers") or row.get("developers") or [],
        "header_image_url": details.get("header_image") or row.get("header_image_url"),
    }


def fetch_steam_enriched_catalogue(limit: int | None = None, path: Path = FIXTURE_PATH,
                                   cache_path: Path = STEAM_CACHE_PATH) -> Iterator[dict]:
    """--source-func entry point for the hosted load: the seed catalogue plus Steam store details."""
    cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    for row in rows_from(load_fixture(path), limit):
        details = cache.get(str(row["source_id"])) if row["source_id"] is not None else None
        if row["source_id"] is not None and details is None:
            log.warning("no cached Steam details for steam:%s (%s); loading unenriched",
                        row["source_id"], row["title"])
        elif details is not None and not details.get("success"):
            log.warning("Steam has no store page for steam:%s (%s); loading unenriched",
                        row["source_id"], row["title"])
        yield enrich(row, details)
