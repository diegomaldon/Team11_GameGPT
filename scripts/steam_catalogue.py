#!/usr/bin/env python3
"""Grow the hosted catalogue to 1000 games from Steam, without RAWG (TM11-159).

The seed fixture has 167 games. The rest come from SteamSpy's ranking of the
most-owned Steam apps, taken in rank order:

  SteamSpy  request=all&page=N        ranking (appid, name, positive/negative reviews)
  SteamSpy  request=appdetails&appid  user tags ("Roguelike", "Cozy", ...) with vote counts
  Steam     api/appdetails            type, description, genres, release date, developers,
                                      publishers, Metacritic, header image, categories

Everything fetched is cached in .cache/catalogue/ (gitignored, ~1.3 MB), so the
load reads files only: it runs offline and two runs from the same cache read the
same data (idempotent). On a fresh clone, step 1 rebuilds the cache from empty,
seed games included.

  # 1. fill the caches until 1000 games are accepted (slow: Steam allows ~200 calls / 5 min)
  python3 scripts/steam_catalogue.py --target 1000

  # 2. load: the 167 seed games first, then ranked Steam games up to --limit
  python3 scripts/ingest_games.py --source-func steam_catalogue:fetch_top_steam_catalogue \\
      --source steam-top --limit 1000 --target 1000

A ranked app is skipped, with its reason logged and written to
artifacts/ingestion/steam-catalogue-skips.json, when it is: not a game (DLC,
software, a soundtrack), adult-only, missing a description, already in the seed
fixture, a repeat of a title already taken, or unknown to Steam. Stdlib only.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import catalogue_source as cs
import steam_store

log = logging.getLogger("steam_catalogue")

RANKING_PATH = cs.CACHE_DIR / "steamspy_ranking.json"
TAGS_PATH = cs.CACHE_DIR / "steamspy_tags.json"
SKIPS_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "ingestion" / "steam-catalogue-skips.json"
STEAMSPY_ALL = "https://steamspy.com/api.php?request=all&page={page}"
STEAMSPY_APP = "https://steamspy.com/api.php?request=appdetails&appid={appid}"
DEFAULT_TARGET = 1000
SPY_ALL_PACE = 61.0   # SteamSpy: one "all" page per 60s
SPY_APP_PACE = 1.1    # SteamSpy: one request per second otherwise
MAX_TAGS = 12
MAX_DESCRIPTION = 1000
MIN_REVIEWS = 50      # fewer and the positive share is noise, so no review_score

# Steam content descriptor ids: 3 = Adult Only Sexual Content, 4 = Frequent Nudity or Sexual Content
ADULT_DESCRIPTORS = {3, 4}
# Steam store genres that mark software, not games
SOFTWARE_GENRES = {"Utilities", "Design & Illustration", "Animation & Modeling", "Video Production",
                   "Audio Production", "Photo Editing", "Software Training", "Web Publishing",
                   "Education", "Game Development", "Accounting"}
# Steam store "genres" that are pricing or release labels, not genres
NOT_GENRES = {"Free to Play", "Free To Play", "Early Access"}
# Steam's game genres, used to read genres out of SteamSpy tags when the store
# lists only a pricing label (The Lab is just "Free To Play" on the store)
STEAM_GENRES = {"Action", "Adventure", "Casual", "Indie", "Massively Multiplayer", "Racing", "RPG",
                "Simulation", "Sports", "Strategy"}
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y", "%B %d, %Y", "%d %B, %Y")


# ----------------------------------------------------------------- mapping

def clean_text(raw: str | None) -> str | None:
    if not raw:
        return None
    text = " ".join(html.unescape(_TAG_RE.sub(" ", raw)).split())
    if len(text) > MAX_DESCRIPTION:
        text = text[:MAX_DESCRIPTION - 3].rstrip() + "..."
    return text or None


def parse_release_date(raw: str | None) -> str | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime((raw or "").strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None   # "Coming soon", "Q3 2026", blank


def review_score(ranked: dict) -> int | None:
    pos, neg = ranked.get("positive") or 0, ranked.get("negative") or 0
    if pos + neg < MIN_REVIEWS:
        return None
    return round(100 * pos / (pos + neg))


def top_tags(votes: dict | None) -> list[str]:
    if not isinstance(votes, dict):
        return []
    ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:MAX_TAGS]]


def skip_reason(details: dict | None) -> str | None:
    """Why a ranked app can't be a catalogue game, or None if it can."""
    if details is None:
        return "no cached Steam details"
    if not details.get("success"):
        return "unknown to Steam"
    if details.get("type") != "game":
        return f"not a game (type {details.get('type')!r})"
    if set(details.get("content_descriptors") or []) & ADULT_DESCRIPTORS:
        return "adult-only content"
    genres = set(details.get("genres") or [])
    if genres & SOFTWARE_GENRES and genres <= SOFTWARE_GENRES | NOT_GENRES:
        return "software, not a game"
    if not clean_text(details.get("short_description")):
        return "no description"
    return None


def genres_for(details: dict, votes: dict | None) -> list[str]:
    genres = [g for g in details.get("genres") or [] if g not in NOT_GENRES]
    if not genres:
        genres = [t for t in top_tags(votes) if t in STEAM_GENRES][:3]
    return genres


def to_row(ranked: dict, details: dict, votes: dict | None) -> dict:
    appid = int(ranked["appid"])
    tags = top_tags(votes)
    seen = {t.casefold() for t in tags}
    for c in details.get("categories") or []:
        if c.casefold() not in seen:
            tags.append(c)
            seen.add(c.casefold())
    return {
        "source": cs.SOURCE,
        "source_id": appid,
        "title": (details.get("name") or ranked.get("name") or "").strip(),
        "description": clean_text(details.get("short_description")),
        "genres": genres_for(details, votes),
        "tags": tags,
        "available_platforms": ["STEAM"],
        "purchase_links": {"STEAM": cs.STEAM_STORE_URL.format(appid=appid)},
        "critic_score": details.get("metacritic"),
        "review_score": review_score(ranked),
        "release_date": parse_release_date(details.get("release_date")),
        "developers": details.get("developers") or [],
        "publishers": details.get("publishers") or [],
        "header_image_url": details.get("header_image"),
    }


# ----------------------------------------------------------------- selection

def select(ranking: list[dict], details: dict[str, dict], tags: dict[str, dict],
           seed_rows: list[dict], target: int) -> tuple[list[dict], list[dict]]:
    """Seed rows first, then ranked games in order until `target`. Returns (rows, skips)."""
    rows = list(seed_rows)
    seed_ids = {r["source_id"] for r in seed_rows}
    titles = {(r["title"] or "").strip().casefold() for r in seed_rows}
    skips: list[dict] = []
    for ranked in ranking:
        if len(rows) >= target:
            break
        appid = int(ranked["appid"])
        if appid in seed_ids:
            continue   # already loaded from the seed fixture, with its curated text
        d = details.get(str(appid))
        reason = skip_reason(d)
        if reason is None:
            row = to_row(ranked, d, tags.get(str(appid)))
            if row["title"].casefold() in titles:
                reason = f"title {row['title']!r} already in the catalogue"
        if reason:
            skips.append({"appid": appid, "name": ranked.get("name"), "reason": reason})
            continue
        titles.add(row["title"].casefold())
        rows.append(row)
    return rows, skips


def _load(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def fetch_top_steam_catalogue(limit: int | None = None) -> Iterator[dict]:
    """--source-func entry point: the enriched seed catalogue, then ranked Steam games."""
    target = limit or DEFAULT_TARGET
    if not RANKING_PATH.exists():
        raise FileNotFoundError(f"no SteamSpy ranking at {RANKING_PATH}; "
                                "run `python scripts/steam_catalogue.py --target N` first")
    seed = list(cs.fetch_steam_enriched_catalogue())
    rows, skips = select(_load(RANKING_PATH, []), steam_store.load_cache(),
                         _load(TAGS_PATH, {}), seed, target)
    for s in skips:
        log.info("skipped steam:%s %r: %s", s["appid"], s["name"], s["reason"])
    if len(rows) < target:
        log.warning("only %d games available for target %d; run steam_catalogue.py to fetch more",
                    len(rows), target)
    SKIPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SKIPS_PATH.write_text(json.dumps(skips, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return iter(rows)


# ----------------------------------------------------------------- fetching

def _get_json(url: str, opener: Callable = urllib.request.urlopen):
    req = urllib.request.Request(url, headers={"User-Agent": steam_store.USER_AGENT})
    with opener(req, timeout=60) as resp:
        return json.load(resp)


def fetch_ranking_page(page: int, get=_get_json) -> list[dict]:
    data = get(STEAMSPY_ALL.format(page=page)) or {}
    out = [{"appid": int(v["appid"]), "name": v.get("name"), "positive": v.get("positive") or 0,
            "negative": v.get("negative") or 0} for v in data.values() if v.get("appid")]
    return out   # SteamSpy returns a page in descending owner order


def fetch_tags(appid: int, get=_get_json) -> dict:
    data = get(STEAMSPY_APP.format(appid=appid)) or {}
    tags = data.get("tags")
    return {k: v for k, v in tags.items() if isinstance(v, int)} if isinstance(tags, dict) else {}


def build_caches(target: int, max_pages: int = 5, sleep: Callable = time.sleep) -> int:
    """Fetch ranking pages, Steam details and SteamSpy tags until `target` games are accepted."""
    ranking: list[dict] = _load(RANKING_PATH, [])
    details = steam_store.load_cache()
    tags: dict[str, dict] = _load(TAGS_PATH, {})
    # the seed games' own Steam details first, so a fresh clone can build from empty
    seed_appids = sorted({e["steam_appid"] for e in cs.load_fixture() if e.get("steam_appid")})
    steam_store.update_cache(seed_appids, details, sleep=sleep, save=steam_store.save_cache)
    steam_store.write_seed_names(details)
    seed = list(cs.fetch_steam_enriched_catalogue())
    pages = max(1, -(-len(ranking) // 1000))
    if not ranking:
        ranking = fetch_ranking_page(0)
        _save(RANKING_PATH, ranking)
    seed_ids = {r["source_id"] for r in seed}
    failed: set[str] = set()   # fetch errors this run; not retried until the next run

    while True:
        rows, skips = select(ranking, details, tags, seed, target)
        gaps = [x for x in skips if x["reason"] == "no cached Steam details" and str(x["appid"]) not in failed]
        if len(rows) >= target and not gaps:
            break   # a ranked app above the cutoff with no details would be left out unfairly
        todo = [r for r in ranking if r["appid"] not in seed_ids and str(r["appid"]) not in failed
                and (str(r["appid"]) not in details
                     or (details[str(r["appid"])].get("success") and str(r["appid"]) not in tags))]
        if not todo:
            if pages >= max_pages:
                log.warning("stopping at %d ranking pages with %d games", pages, len(rows))
                break
            sleep(SPY_ALL_PACE)
            ranking += [r for r in fetch_ranking_page(pages) if r["appid"] not in {x["appid"] for x in ranking}]
            pages += 1
            _save(RANKING_PATH, ranking)
            continue
        # fetch the next chunk, in rank order, then re-check the target
        need = target - len(rows)
        for n, r in enumerate(todo[: need + 20], 1):
            key = str(r["appid"])
            if key not in details:
                try:
                    details[key] = steam_store.fetch_appdetails(r["appid"])
                except Exception as exc:  # noqa: BLE001 - logged; a rerun retries it
                    log.error("appdetails %s failed: %s", key, exc)
                    failed.add(key)
                    continue
                sleep(steam_store.PACE_SECONDS)
            if details[key].get("success") and details[key].get("type") == "game" and key not in tags:
                try:
                    tags[key] = fetch_tags(r["appid"])
                except Exception as exc:  # noqa: BLE001 - not cached, so a rerun retries it
                    log.error("steamspy tags %s failed: %s", key, exc)
                    failed.add(key)
                    continue
                sleep(SPY_APP_PACE)
            elif key not in tags:
                tags[key] = {}
            if n % 25 == 0:
                steam_store.save_cache(details)
                _save(TAGS_PATH, tags)
                log.info("fetched %d of this chunk; %d games so far", n,
                         len(select(ranking, details, tags, seed, target)[0]))
        steam_store.save_cache(details)
        _save(TAGS_PATH, tags)
    rows, skips = select(ranking, details, tags, seed, target)
    print(f"steam_catalogue: {len(rows)} games accepted for target {target} "
          f"({len(seed)} seed, {len(rows) - len(seed)} ranked); {len(skips)} ranked apps skipped.")
    return len(rows)


def _save(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, dict):
        data = {k: data[k] for k in sorted(data, key=int)}
    Path(path).write_text(json.dumps(data, indent=None if isinstance(data, list) else 1,
                                     ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=DEFAULT_TARGET)
    ap.add_argument("--max-pages", type=int, default=5)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return 0 if build_caches(a.target, a.max_pages) >= a.target else 1


if __name__ == "__main__":
    sys.exit(main())
